package transmitter

import (
	"os/exec"
	"strings"
)

func pickH264Encoder() string {
	available := ffmpegEncoders()
	candidates := []string{
		"libx264",
		"libopenh264",
		"h264_v4l2m2m",
		"h264_qsv",
		"h264_vaapi",
		"h264_nvenc",
		"h264_amf",
	}
	for _, name := range candidates {
		if strings.Contains(available, name) {
			return name
		}
	}
	return "libx264"
}

func ffmpegEncoders() string {
	out, err := exec.Command("ffmpeg", "-hide_banner", "-encoders").CombinedOutput()
	if err != nil {
		return ""
	}
	return string(out)
}
