package receiver

import "fmt"

func parseH264SPSDimensions(nal []byte) (int, int, error) {
	if len(nal) < 4 {
		return 0, 0, fmt.Errorf("short SPS")
	}

	// Remove NAL header and emulation prevention bytes.
	rbsp := make([]byte, 0, len(nal)-1)
	for i := 1; i < len(nal); i++ {
		if i+2 < len(nal) && nal[i] == 0x00 && nal[i+1] == 0x00 && nal[i+2] == 0x03 {
			rbsp = append(rbsp, 0x00, 0x00)
			i += 2
			continue
		}
		rbsp = append(rbsp, nal[i])
	}

	br := newSPSBitReader(rbsp)

	profileIDC, ok := br.readBits(8)
	if !ok {
		return 0, 0, fmt.Errorf("invalid profile_idc")
	}
	if _, ok := br.readBits(8); !ok { // constraint flags + reserved
		return 0, 0, fmt.Errorf("invalid constraints")
	}
	if _, ok := br.readBits(8); !ok { // level_idc
		return 0, 0, fmt.Errorf("invalid level_idc")
	}
	if _, ok := br.readUE(); !ok { // seq_parameter_set_id
		return 0, 0, fmt.Errorf("invalid sps id")
	}

	chromaFormatIDC := 1
	switch profileIDC {
	case 100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135:
		v, ok := br.readUE()
		if !ok {
			return 0, 0, fmt.Errorf("invalid chroma_format_idc")
		}
		chromaFormatIDC = v
		if chromaFormatIDC == 3 {
			if _, ok := br.readBits(1); !ok { // separate_colour_plane_flag
				return 0, 0, fmt.Errorf("invalid separate_colour_plane_flag")
			}
		}
		if _, ok := br.readUE(); !ok { // bit_depth_luma_minus8
			return 0, 0, fmt.Errorf("invalid bit_depth_luma_minus8")
		}
		if _, ok := br.readUE(); !ok { // bit_depth_chroma_minus8
			return 0, 0, fmt.Errorf("invalid bit_depth_chroma_minus8")
		}
		if _, ok := br.readBits(1); !ok { // qpprime_y_zero_transform_bypass_flag
			return 0, 0, fmt.Errorf("invalid qpprime flag")
		}
		seqScalingMatrixPresent, ok := br.readBits(1)
		if !ok {
			return 0, 0, fmt.Errorf("invalid seq_scaling_matrix_present_flag")
		}
		if seqScalingMatrixPresent == 1 {
			count := 8
			if chromaFormatIDC == 3 {
				count = 12
			}
			for i := 0; i < count; i++ {
				present, ok := br.readBits(1)
				if !ok {
					return 0, 0, fmt.Errorf("invalid scaling list present")
				}
				if present == 1 {
					size := 16
					if i >= 6 {
						size = 64
					}
					if !skipScalingList(br, size) {
						return 0, 0, fmt.Errorf("invalid scaling list")
					}
				}
			}
		}
	}

	if _, ok := br.readUE(); !ok { // log2_max_frame_num_minus4
		return 0, 0, fmt.Errorf("invalid log2_max_frame_num_minus4")
	}
	picOrderCntType, ok := br.readUE()
	if !ok {
		return 0, 0, fmt.Errorf("invalid pic_order_cnt_type")
	}
	if picOrderCntType == 0 {
		if _, ok := br.readUE(); !ok { // log2_max_pic_order_cnt_lsb_minus4
			return 0, 0, fmt.Errorf("invalid log2_max_pic_order_cnt_lsb_minus4")
		}
	} else if picOrderCntType == 1 {
		if _, ok := br.readBits(1); !ok { // delta_pic_order_always_zero_flag
			return 0, 0, fmt.Errorf("invalid delta flag")
		}
		if _, ok := br.readSE(); !ok { // offset_for_non_ref_pic
			return 0, 0, fmt.Errorf("invalid offset_for_non_ref_pic")
		}
		if _, ok := br.readSE(); !ok { // offset_for_top_to_bottom_field
			return 0, 0, fmt.Errorf("invalid offset_for_top_to_bottom_field")
		}
		numRefFramesInPicOrderCntCycle, ok := br.readUE()
		if !ok {
			return 0, 0, fmt.Errorf("invalid num_ref_frames_in_pic_order_cnt_cycle")
		}
		for i := 0; i < numRefFramesInPicOrderCntCycle; i++ {
			if _, ok := br.readSE(); !ok {
				return 0, 0, fmt.Errorf("invalid offset_for_ref_frame")
			}
		}
	}

	if _, ok := br.readUE(); !ok { // max_num_ref_frames
		return 0, 0, fmt.Errorf("invalid max_num_ref_frames")
	}
	if _, ok := br.readBits(1); !ok { // gaps_in_frame_num_value_allowed_flag
		return 0, 0, fmt.Errorf("invalid gaps_in_frame_num flag")
	}
	picWidthInMbsMinus1, ok := br.readUE()
	if !ok {
		return 0, 0, fmt.Errorf("invalid pic_width_in_mbs_minus1")
	}
	picHeightInMapUnitsMinus1, ok := br.readUE()
	if !ok {
		return 0, 0, fmt.Errorf("invalid pic_height_in_map_units_minus1")
	}
	frameMbsOnlyFlag, ok := br.readBits(1)
	if !ok {
		return 0, 0, fmt.Errorf("invalid frame_mbs_only_flag")
	}
	if frameMbsOnlyFlag == 0 {
		if _, ok := br.readBits(1); !ok { // mb_adaptive_frame_field_flag
			return 0, 0, fmt.Errorf("invalid mb_adaptive_frame_field_flag")
		}
	}
	if _, ok := br.readBits(1); !ok { // direct_8x8_inference_flag
		return 0, 0, fmt.Errorf("invalid direct_8x8_inference_flag")
	}

	frameCropLeftOffset := 0
	frameCropRightOffset := 0
	frameCropTopOffset := 0
	frameCropBottomOffset := 0
	frameCroppingFlag, ok := br.readBits(1)
	if !ok {
		return 0, 0, fmt.Errorf("invalid frame_cropping_flag")
	}
	if frameCroppingFlag == 1 {
		if frameCropLeftOffset, ok = br.readUE(); !ok {
			return 0, 0, fmt.Errorf("invalid frame_crop_left_offset")
		}
		if frameCropRightOffset, ok = br.readUE(); !ok {
			return 0, 0, fmt.Errorf("invalid frame_crop_right_offset")
		}
		if frameCropTopOffset, ok = br.readUE(); !ok {
			return 0, 0, fmt.Errorf("invalid frame_crop_top_offset")
		}
		if frameCropBottomOffset, ok = br.readUE(); !ok {
			return 0, 0, fmt.Errorf("invalid frame_crop_bottom_offset")
		}
	}

	width := (picWidthInMbsMinus1 + 1) * 16
	height := (picHeightInMapUnitsMinus1 + 1) * 16
	if frameMbsOnlyFlag == 0 {
		height *= 2
	}

	cropUnitX := 1
	cropUnitY := 2 - int(frameMbsOnlyFlag)
	switch chromaFormatIDC {
	case 0:
		cropUnitX = 1
		cropUnitY = 2 - int(frameMbsOnlyFlag)
	case 1:
		cropUnitX = 2
		cropUnitY = 2 * (2 - int(frameMbsOnlyFlag))
	case 2:
		cropUnitX = 2
		cropUnitY = 2 - int(frameMbsOnlyFlag)
	case 3:
		cropUnitX = 1
		cropUnitY = 2 - int(frameMbsOnlyFlag)
	}

	width -= cropUnitX * (frameCropLeftOffset + frameCropRightOffset)
	height -= cropUnitY * (frameCropTopOffset + frameCropBottomOffset)
	if width <= 0 || height <= 0 {
		return 0, 0, fmt.Errorf("invalid computed dimensions")
	}

	return width, height, nil
}

func skipScalingList(br *spsBitReader, size int) bool {
	lastScale := 8
	nextScale := 8
	for j := 0; j < size; j++ {
		if nextScale != 0 {
			deltaScale, ok := br.readSE()
			if !ok {
				return false
			}
			nextScale = (lastScale + deltaScale + 256) % 256
		}
		if nextScale != 0 {
			lastScale = nextScale
		}
	}
	return true
}

type spsBitReader struct {
	data []byte
	bit  int
}

func newSPSBitReader(data []byte) *spsBitReader {
	return &spsBitReader{data: data}
}

func (b *spsBitReader) readBits(n int) (uint, bool) {
	if n <= 0 || n > 32 {
		return 0, false
	}
	var out uint
	for i := 0; i < n; i++ {
		bit, ok := b.readBit()
		if !ok {
			return 0, false
		}
		out = (out << 1) | uint(bit)
	}
	return out, true
}

func (b *spsBitReader) readBit() (uint8, bool) {
	if b.bit >= len(b.data)*8 {
		return 0, false
	}
	byteIdx := b.bit / 8
	bitIdx := 7 - (b.bit % 8)
	v := (b.data[byteIdx] >> bitIdx) & 0x01
	b.bit++
	return v, true
}

func (b *spsBitReader) readUE() (int, bool) {
	zeros := 0
	for {
		bit, ok := b.readBit()
		if !ok {
			return 0, false
		}
		if bit == 1 {
			break
		}
		zeros++
		if zeros > 31 {
			return 0, false
		}
	}
	codeNum := 1
	for i := 0; i < zeros; i++ {
		bit, ok := b.readBit()
		if !ok {
			return 0, false
		}
		codeNum = (codeNum << 1) | int(bit)
	}
	return codeNum - 1, true
}

func (b *spsBitReader) readSE() (int, bool) {
	ue, ok := b.readUE()
	if !ok {
		return 0, false
	}
	value := (ue + 1) / 2
	if ue%2 == 0 {
		value = -value
	}
	return value, true
}
