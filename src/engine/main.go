package main

import (
	"context"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os/signal"
	"syscall"
	"time"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/BarrettBr/HackKU-2026/registry"
)

func main() {
	if err := run(); err != nil {
		log.Fatalf("Engine startup failed: %v", err)
	}
}

func run() error {
	appCfg, err := config.Load()
	if err != nil {
		return fmt.Errorf("build config: %w", err)
	}

	appRegistry, err := registry.New(appCfg)
	if err != nil {
		return fmt.Errorf("create registry: %w", err)
	}

	server := setupAPIServer(appCfg, appRegistry)
	log.Printf("Engine API listening on %s", server.Addr)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	// Start a goroutine that when a shutdown occurs will tell the other apps to shutdown
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdownCtx)
		_ = appRegistry.Stop()
	}()

	// Startup API server
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		return fmt.Errorf("api server failed: %w", err)
	}

	return nil
}
