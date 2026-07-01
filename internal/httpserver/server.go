package httpserver

import (
	"context"
	"encoding/json"
	"net/http"
	"runtime"
	"time"
)

type ReadinessChecker interface {
	Ready(ctx context.Context) error
}

func NewHandler(
	mcpHandler http.Handler,
	a2aHandler http.Handler,
	checker ReadinessChecker,
) http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /healthz", healthz)
	mux.HandleFunc("GET /readyz", readyz(checker))
	mux.HandleFunc("GET /debug/runtime-metrics", runtimeMetrics)
	mux.Handle("/mcp", mcpHandler)
	mux.Handle("GET /.well-known/agent-card.json", a2aHandler)
	mux.Handle("POST /tasks", a2aHandler)

	return mux
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
