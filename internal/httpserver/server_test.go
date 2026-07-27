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
		http.NotFoundHandler(),
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

func TestMCPPreflightHandlesCORS(t *testing.T) {
	mcpCalled := false
	mcpHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mcpCalled = true
		w.WriteHeader(http.StatusAccepted)
	})

	handler := NewHandler(
		mcpHandler,
		http.NotFoundHandler(),
		fakeChecker{},
		WithCORSAllowedOrigins("http://127.0.0.1:8080"),
	)

	request := httptest.NewRequest(http.MethodOptions, "/mcp", nil)
	request.Header.Set("Origin", "http://127.0.0.1:8080")
	request.Header.Set("Access-Control-Request-Method", http.MethodPost)
	request.Header.Set("Access-Control-Request-Headers", "authorization, content-type, accept, mcp-session-id")
	response := httptest.NewRecorder()

	handler.ServeHTTP(response, request)

	if mcpCalled {
		t.Fatal("MCP handler was called for CORS preflight")
	}
	if response.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusNoContent)
	}
	if got := response.Header().Get("Access-Control-Allow-Origin"); got != "http://127.0.0.1:8080" {
		t.Fatalf("Access-Control-Allow-Origin = %q", got)
	}
	if got := response.Header().Get("Access-Control-Allow-Methods"); got != corsAllowedMethods {
		t.Fatalf("Access-Control-Allow-Methods = %q, want %q", got, corsAllowedMethods)
	}
	if got := response.Header().Get("Access-Control-Allow-Headers"); got != corsAllowedHeaders {
		t.Fatalf("Access-Control-Allow-Headers = %q, want %q", got, corsAllowedHeaders)
	}
}

func TestMCPResponseExposesSessionHeaderForCORS(t *testing.T) {
	mcpHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Mcp-Session-Id", "session-123")
		w.WriteHeader(http.StatusOK)
	})

	handler := NewHandler(
		mcpHandler,
		http.NotFoundHandler(),
		fakeChecker{},
		WithCORSAllowedOrigins("http://127.0.0.1:8080"),
	)

	request := httptest.NewRequest(http.MethodPost, "/mcp", nil)
	request.Header.Set("Origin", "http://127.0.0.1:8080")
	response := httptest.NewRecorder()

	handler.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusOK)
	}
	if got := response.Header().Get("Access-Control-Allow-Origin"); got != "http://127.0.0.1:8080" {
		t.Fatalf("Access-Control-Allow-Origin = %q", got)
	}
	if got := response.Header().Get("Access-Control-Expose-Headers"); got != "Mcp-Session-Id" {
		t.Fatalf("Access-Control-Expose-Headers = %q", got)
	}
	if got := response.Header().Get("Mcp-Session-Id"); got != "session-123" {
		t.Fatalf("Mcp-Session-Id = %q", got)
	}
}

func TestCORSRejectsDisallowedPreflight(t *testing.T) {
	mcpCalled := false
	mcpHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mcpCalled = true
		w.WriteHeader(http.StatusAccepted)
	})

	handler := NewHandler(
		mcpHandler,
		http.NotFoundHandler(),
		fakeChecker{},
		WithCORSAllowedOrigins("http://127.0.0.1:8080"),
	)

	request := httptest.NewRequest(http.MethodOptions, "/mcp", nil)
	request.Header.Set("Origin", "https://app.example.test")
	request.Header.Set("Access-Control-Request-Method", http.MethodPost)
	response := httptest.NewRecorder()

	handler.ServeHTTP(response, request)

	if mcpCalled {
		t.Fatal("MCP handler was called for rejected CORS preflight")
	}
	if response.Code != http.StatusForbidden {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusForbidden)
	}
	if got := response.Header().Get("Access-Control-Allow-Origin"); got != "" {
		t.Fatalf("Access-Control-Allow-Origin = %q, want empty", got)
	}
}
