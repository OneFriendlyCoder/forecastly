// Command api serves deals and their scores from Postgres over read-only HTTP.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	defaultLimit = 50
	maxLimit     = 1000
	queryTimeout = 5 * time.Second
)

const latestScore = `
    SELECT s.score, s.as_of, s.model_version, s.factors, s.features
    FROM deal_scores s WHERE s.deal_id = d.deal_id
    ORDER BY s.as_of DESC, s.scored_at DESC LIMIT 1`

// Postgres builds each JSON response, so the columns live in one place.
const atRiskSQL = `
SELECT json_build_object('deals', coalesce(json_agg(t ORDER BY t.score, t.deal_id), '[]'))::text
FROM (
    SELECT d.deal_id, d.product, d.amount, s.score, s.as_of, s.model_version, s.factors
    FROM deal_health h
    JOIN deals d USING (deal_id)
    CROSS JOIN LATERAL (` + latestScore + `) s
    WHERE h.deal_closed = 0
    ORDER BY s.score, d.deal_id
    LIMIT $1
) t`

const dealSQL = `
SELECT row_to_json(t)::text
FROM (
    SELECT d.deal_id, d.product, d.amount, coalesce(h.deal_closed > 0, false) AS closed, h.last_event_at,
           s.score, s.as_of, s.model_version, s.factors, s.features,
           to_jsonb(h) - 'deal_id' - 'last_event_at' - 'last_event_id' - 'updated_at' AS activity
    FROM deals d
    LEFT JOIN deal_health h USING (deal_id)
    LEFT JOIN LATERAL (` + latestScore + `) s ON true
    WHERE d.deal_id = $1
) t`

// The newest scores, returned oldest first so a chart can draw them in order.
const scoresSQL = `
SELECT json_build_object('deal_id', d.deal_id, 'scores', (
    SELECT coalesce(json_agg(t ORDER BY t.as_of), '[]')
    FROM (
        SELECT s.as_of, s.score, s.model_version FROM deal_scores s
        WHERE s.deal_id = d.deal_id ORDER BY s.as_of DESC LIMIT $2
    ) t
))::text
FROM deals d WHERE d.deal_id = $1`

type server struct {
	db *pgxpool.Pool
}

func writeError(w http.ResponseWriter, status int, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	w.Write([]byte(`{"error":"` + message + `"}`))
}

// parseLimit returns false for anything but a whole number from 1 to maxLimit.
func parseLimit(r *http.Request) (int, bool) {
	text := r.URL.Query().Get("limit")
	if text == "" {
		return defaultLimit, true
	}
	limit, err := strconv.Atoi(text)
	return limit, err == nil && limit >= 1 && limit <= maxLimit
}

// respond runs a query that returns one row of JSON. No row means the deal doesn't exist.
func (s *server) respond(w http.ResponseWriter, r *http.Request, query string, args ...any) {
	ctx, cancel := context.WithTimeout(r.Context(), queryTimeout)
	defer cancel()
	var body string
	err := s.db.QueryRow(ctx, query, args...).Scan(&body)
	if errors.Is(err, pgx.ErrNoRows) {
		writeError(w, http.StatusNotFound, "deal not found")
		return
	}
	if err != nil {
		slog.Error("query failed", "path", r.URL.Path, "error", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(body))
}

func (s *server) atRisk(w http.ResponseWriter, r *http.Request) {
	limit, ok := parseLimit(r)
	if !ok {
		writeError(w, http.StatusBadRequest, "limit must be from 1 to 1000")
		return
	}
	s.respond(w, r, atRiskSQL, limit)
}

func (s *server) deal(w http.ResponseWriter, r *http.Request) {
	s.respond(w, r, dealSQL, r.PathValue("id"))
}

func (s *server) scores(w http.ResponseWriter, r *http.Request) {
	limit, ok := parseLimit(r)
	if !ok {
		writeError(w, http.StatusBadRequest, "limit must be from 1 to 1000")
		return
	}
	s.respond(w, r, scoresSQL, r.PathValue("id"), limit)
}

func (s *server) health(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), queryTimeout)
	defer cancel()
	if err := s.db.Ping(ctx); err != nil {
		writeError(w, http.StatusServiceUnavailable, "database unavailable")
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Write([]byte(`{"status":"ok"}`))
}

func (s *server) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", s.health)
	mux.HandleFunc("GET /deals/at-risk", s.atRisk)
	mux.HandleFunc("GET /deals/{id}", s.deal)
	mux.HandleFunc("GET /deals/{id}/scores", s.scores)
	return mux
}

func getenv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func run(ctx context.Context) error {
	db, err := pgxpool.New(ctx, getenv("DATABASE_URL", "postgres://pulse:pulse@localhost:5432/pipeline_pulse"))
	if err != nil {
		return err
	}
	defer db.Close()

	httpServer := &http.Server{
		Addr:              getenv("LISTEN_ADDR", ":8080"),
		Handler:           (&server{db: db}).routes(),
		ReadHeaderTimeout: 5 * time.Second,
		WriteTimeout:      2 * queryTimeout,
	}
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), queryTimeout)
		defer cancel()
		httpServer.Shutdown(shutdown)
	}()
	slog.Info("listening", "addr", httpServer.Addr)
	if err := httpServer.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return nil
}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := run(ctx); err != nil {
		slog.Error("api stopped", "error", err)
		os.Exit(1)
	}
}
