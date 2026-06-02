package httpserver

// This file intentionally keeps the old Gin experiment as comments only.
// The project uses the standard library HTTP server to avoid an extra dependency.

// package httpserver

// import (
// 	"context"
// 	"net/http"
// 	"time"

// 	"github.com/gin-gonic/gin"
// )

// type ReadinessChecker interface {
// 	Ready(ctx context.Context) error
// }

// func NewHandler(
// 	mcpHandler http.Handler,
// 	checker ReadinessChecker,
// ) http.Handler {
// 	router := gin.New()
// 	router.Use(gin.Recovery())
// 	router.GET("/healthz", healthz)
// 	router.GET("/readyz", readyz(checker))
// 	router.Any("/mcp", gin.WrapH(mcpHandler))

// 	return router
// }

// // func init() {
// // 	r := gin.Default()
// // 	r.Handle(http.MethodGet, "/healthz", healthz)
// // 	r.Handler(http.MethonGet)
// // }

// func healthz(c *gin.Context) {
// 	c.JSON(http.StatusOK, gin.H{
// 		"status": "ok",
// 	})
// }
// func readyz(checker ReadinessChecker) gin.HandlerFunc {
// 	return func(c *gin.Context) {
// 		ctx, cancel := context.WithTimeout(c.Request.Context(), time.Second)
// 		defer cancel()

// 		if err := checker.Ready(ctx); err != nil {
// 			c.JSON(http.StatusServiceUnavailable, gin.H{
// 				"status": "not_ready",
// 				"reason": err.Error(),
// 			})
// 			return
// 		}

// 		c.JSON(http.StatusOK, gin.H{
// 			"status": "ready",
// 		})
// 	}

// }
