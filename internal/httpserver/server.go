package httpserver

import (
	"context"
	"encoding/json"
	"net/http"
	"runtime"
	"time"
)

const (
	corsAllowedMethods = "GET, POST, DELETE, OPTIONS"
	corsAllowedHeaders = "Authorization, Content-Type, Accept, A2A-Version, A2A-Extensions, Mcp-Protocol-Version, Mcp-Session-Id, Mcp-Method, Mcp-Name, Last-Event-ID"
	corsExposedHeaders = "Mcp-Session-Id"
	corsMaxAgeSeconds  = "600"
)

type ReadinessChecker interface {
	Ready(ctx context.Context) error
}

type handlerOptions struct {
	corsAllowedOrigins []string
}

type Option func(*handlerOptions)

func WithCORSAllowedOrigins(origins ...string) Option {
	return func(options *handlerOptions) {
		options.corsAllowedOrigins = append([]string(nil), origins...)
	}
}

func NewHandler(
	mcpHandler http.Handler,
	a2aHandler http.Handler,
	checker ReadinessChecker,
	opts ...Option,
) http.Handler {
	options := handlerOptions{}
	for _, opt := range opts {
		opt(&options)
	}

	mux := http.NewServeMux()

	mux.HandleFunc("GET /healthz", healthz)
	mux.HandleFunc("GET /readyz", readyz(checker))
	mux.HandleFunc("GET /debug/runtime-metrics", runtimeMetrics)
	mux.Handle("/mcp", mcpHandler)
	mux.Handle("GET /.well-known/agent-card.json", a2aHandler)
	mux.Handle("POST /a2a", a2aHandler)
	mux.Handle("POST /tasks", a2aHandler)

	if len(options.corsAllowedOrigins) == 0 {
		return mux
	}

	return withCORS(mux, options.corsAllowedOrigins)
}

func withCORS(next http.Handler, allowedOrigins []string) http.Handler {
	allowed := make(map[string]struct{}, len(allowedOrigins))
	for _, origin := range allowedOrigins {
		if origin == "" {
			continue
		}
		allowed[origin] = struct{}{}
	}

	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if origin == "" {
			next.ServeHTTP(w, r)
			return
		}

		header := w.Header()
		header.Add("Vary", "Origin")
		header.Add("Vary", "Access-Control-Request-Method")
		header.Add("Vary", "Access-Control-Request-Headers")

		if _, ok := allowed[origin]; !ok {
			if r.Method == http.MethodOptions {
				http.Error(w, "CORS origin is not allowed", http.StatusForbidden)
				return
			}

			next.ServeHTTP(w, r)
			return
		}

		header.Set("Access-Control-Allow-Origin", origin)
		header.Set("Access-Control-Allow-Methods", corsAllowedMethods)
		header.Set("Access-Control-Allow-Headers", corsAllowedHeaders)
		header.Set("Access-Control-Expose-Headers", corsExposedHeaders)
		header.Set("Access-Control-Max-Age", corsMaxAgeSeconds)

		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}

		next.ServeHTTP(w, r)
	})
}

// runtimeMetrics exposes Go runtime allocation/GC counters so an experiment
// harness can read them before and after a task and record the server-side
// delta (TotalAlloc is monotonic, so its delta is a low-noise "work done"
// proxy that is unaffected by GC timing).
func runtimeMetrics(w http.ResponseWriter, r *http.Request) {
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
	writeJSON(w, http.StatusOK, map[string]any{
		"total_alloc_bytes": m.TotalAlloc,
		"heap_alloc_bytes":  m.HeapAlloc,
		"sys_bytes":         m.Sys,
		"mallocs":           m.Mallocs,
		"frees":             m.Frees,
		"num_gc":            m.NumGC,
		"num_goroutine":     runtime.NumGoroutine(),
	})
}

func healthz(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{
		"status": "ok",
	})
}

func readyz(checker ReadinessChecker) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), time.Second)
		defer cancel()

		if err := checker.Ready(ctx); err != nil {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{
				"status": "not_ready",
				"reason": err.Error(),
			})
			return
		}

		writeJSON(w, http.StatusOK, map[string]string{
			"status": "ready",
		})
	}
}

func writeJSON(
	w http.ResponseWriter,
	status int,
	value any,
) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)

	_ = json.NewEncoder(w).Encode(value)
}
