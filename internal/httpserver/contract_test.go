package httpserver

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
)

// TestRouteContract pins the gateway's complete HTTP route surface as a single
// regression baseline. The pre-A2A baseline recorded `/.well-known/agent-card.json`
// and `/tasks` as 404 (not yet mounted); now that the store-agent arm has landed,
// those rows assert the routes are delegated to the a2aHandler — the visible record
// that the change was additive and the existing Arm A/B surface (health, readiness,
// /mcp) still behaves identically.
func TestRouteContract(t *testing.T) {
	const mcpStatus = http.StatusAccepted
	const a2aStatus = http.StatusAccepted

	cases := []struct {
		name          string
		method        string
		path          string
		checkerErr    error
		wantStatus    int
		wantMCPCalled bool
		wantA2ACalled bool
	}{
		{"health always ok", http.MethodGet, "/healthz", nil, http.StatusOK, false, false},
		{"readiness upstream up", http.MethodGet, "/readyz", nil, http.StatusOK, false, false},
		{"readiness upstream down", http.MethodGet, "/readyz", errors.New("upstream down"), http.StatusServiceUnavailable, false, false},
		{"runtime metrics ok", http.MethodGet, "/debug/runtime-metrics", nil, http.StatusOK, false, false},
		{"mcp route delegates", http.MethodPost, "/mcp", nil, mcpStatus, true, false},
		{"a2a agent card delegates", http.MethodGet, "/.well-known/agent-card.json", nil, a2aStatus, false, true},
		{"a2a tasks delegates", http.MethodPost, "/tasks", nil, a2aStatus, false, true},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			mcpCalled := false
			mcpHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				mcpCalled = true
				w.WriteHeader(mcpStatus)
			})

			a2aCalled := false
			a2aHandler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				a2aCalled = true
				w.WriteHeader(a2aStatus)
			})

			handler := NewHandler(mcpHandler, a2aHandler, fakeChecker{err: tc.checkerErr})

			request := httptest.NewRequest(tc.method, tc.path, nil)
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, request)

			if response.Code != tc.wantStatus {
				t.Fatalf("%s %s: status = %d, want %d", tc.method, tc.path, response.Code, tc.wantStatus)
			}
			if mcpCalled != tc.wantMCPCalled {
				t.Fatalf("%s %s: mcp delegated = %v, want %v", tc.method, tc.path, mcpCalled, tc.wantMCPCalled)
			}
			if a2aCalled != tc.wantA2ACalled {
				t.Fatalf("%s %s: a2a delegated = %v, want %v", tc.method, tc.path, a2aCalled, tc.wantA2ACalled)
			}
		})
	}
}
