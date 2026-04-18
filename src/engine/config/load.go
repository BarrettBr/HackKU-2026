package config

import(
	"log"
)

type Config struct {
}


func load() (*Config, error){
	appCfg, err := loadSettings()
	if(err != nil){
		log.Fatalf("Error building config: %v", err)
	}

	return appCfg, nil
}

func loadSettings() (*Config, error){
	return &Config{
	}, nil
}
