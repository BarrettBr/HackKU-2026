package main

import (
	"log"

	"github.com/BarrettBr/HackKU-2026/config"
	"github.com/BarrettBr/HackKU-2026/registry"
)

func main() {
	appCfg, err := config.Load()
	if err != nil {
		log.Fatalf("Error building config: %v", err)
	}

	appRegistry, err := registry.New(appCfg)
	if err != nil {
		log.Fatalf("Error creating registry: %v", err)
	}

	if err := appRegistry.Run(); err != nil {
		log.Fatalf("Error running registry: %v", err)
	}
}
