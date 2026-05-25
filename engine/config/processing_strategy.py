from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProcessingStrategy:
    """Rule-driven visual processing strengths for one image."""

    noise_reduction_strength: float = 0.35
    high_frequency_control_strength: float = 0.35
    mid_frequency_restore_strength: float = 0.35
    light_compression_strength: float = 0.35
    atmosphere_strength: float = 0.35
    color_harmony_strength: float = 0.35
    sharpen_strength: float = 0.12
    texture_cleanliness_target: float = 0.72
    premium_style_target: float = 0.72

    def to_dict(self) -> dict[str, float]:
        return asdict(self)
