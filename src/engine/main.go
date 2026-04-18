package main

import (
	"log"
	"github.com/BarrettBr/eecs-582-capstone/internal/config"
)

func main(){
	appCfg, err := config.load();
	if err != nil {
		log.Fatalf("Error building config: %v", err)
	}

}
