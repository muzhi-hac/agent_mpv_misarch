package httpserver

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

type fakeChecker struct {
	err error
}

func (f fakeChecker) Ready(ctx context.Context) error {
	return f.err
}

func TestHealthz(t *testing.T) {
	handler := NewHandler(
		http.NotFoundHandler(),
		fakeChecker{},
	)

	request := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	response := httptest.NewRecorder()

	handler.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusOK)
	}

	if !strings.Contains(response.Body.String(), `"status":"ok"`) {
		t.Fatalf("body = %q", response.Body.String())
	}
}

func TestReadyzSuccess(t *testing.T) {
	handler := NewHandler(
		http.NotFoundHandler(),
		fakeChecker{},
	)

	request := httptest.NewRequest(http.MethodGet, "/readyz", nil)
	response := httptest.NewRecorder()

	handler.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusOK)
	}

	if !strings.Contains(response.Body.String(), `"status":"ready"`) {
		t.Fatalf("body = %q", response.Body.String())
	}
}

func TestReadyzFailure(t *testing.T) {
	handler := NewHandler(
		http.NotFoundHandler(),
		fakeChecker{
			err: errors.New("upstream unavailable"),
		},
	)

	request := httptest.NewRequest(http.MethodGet, "/readyz", nil)
	response := httptest.NewRecorder()

	handler.ServeHTTP(response, request)

	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf(
			"status = %d, want %d",
			response.Code,
			http.StatusServiceUnavailable,
		)
	}

	if !strings.Contains(response.Body.String(), "upstream unavailable") {
		t.Fatalf("body = %q", response.Body.String())
	}
}

func TestMCPRouteIsMounted(t *testing.T) {
	mcpCalled := false

	mcpHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mcpCalled = true
		w.WriteHeader(http.StatusAccepted)
	})

	handler := NewHandler(
		mcpHandler,
		fakeChecker{},
	)

	request := httptest.NewRequest(http.MethodPost, "/mcp", nil)
	response := httptest.NewRecorder()

	handler.ServeHTTP(response, request)

	if !mcpCalled {
		t.Fatal("MCP handler was not called")
	}

	if response.Code != http.StatusAccepted {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusAccepted)
	}
}
