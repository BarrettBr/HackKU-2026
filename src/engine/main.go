package main

import (
	"log"

	"github.com/BarrettBr/HackKU-2026/config"
)

func main() {
	appCfg, err := config.Load()
	if err != nil {
		log.Fatalf("Error building config: %v", err)
	}
	_ = appCfg
}
