//go:build !pipewire

package recording

import (
	"fmt"

	"github.com/BarrettBr/HackKU-2026/config"
)

func NewStream(cfg *config.Config) (ScreenStream, error) {
	_ = cfg
	return nil, fmt.Errorf("pipewire capture disabled: rebuild with -tags pipewire")
}
