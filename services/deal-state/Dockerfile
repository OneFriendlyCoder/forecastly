FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY schemas schemas
COPY services/deal-state services/deal-state
RUN CGO_ENABLED=0 go build -o /deal-state ./services/deal-state

FROM alpine:3.22
RUN adduser -D app
USER app
COPY --from=build /deal-state /deal-state
ENTRYPOINT ["/deal-state"]
