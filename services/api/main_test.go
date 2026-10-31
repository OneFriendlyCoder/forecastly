package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestBadLimitsAreRejectedBeforeAnyQuery(t *testing.T) {
	routes := (&server{}).routes() // no database: reaching one would panic
	for _, path := range []string{"/deals/at-risk", "/deals/d1/scores"} {
		for _, limit := range []string{"0", "-1", "1001", "abc", "1.5"} {
			response := httptest.NewRecorder()
			routes.ServeHTTP(response, httptest.NewRequest(http.MethodGet, path+"?limit="+limit, nil))
			if response.Code != http.StatusBadRequest {
				t.Errorf("%s limit=%s: got %d", path, limit, response.Code)
			}
		}
	}
}

func TestOnlyGetIsAllowed(t *testing.T) {
	response := httptest.NewRecorder()
	(&server{}).routes().ServeHTTP(response, httptest.NewRequest(http.MethodPost, "/deals/at-risk", nil))
	if response.Code != http.StatusMethodNotAllowed {
		t.Errorf("got %d", response.Code)
	}
}
