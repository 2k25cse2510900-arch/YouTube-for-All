"""Domain exceptions for Pipeline Orchestration and Safety Gating."""


class PipelineError(Exception):
    """Base exception for all pipeline orchestration errors."""

    pass


class ScriptNotApprovedError(PipelineError):
    """Raised when an unapproved, pending, or rejected script is requested for production (Gate A)."""

    pass


class ScientificClaimUnverifiedError(PipelineError):
    """Raised when anime science claims lack independent human verification (Gate B)."""

    pass


class StoryboardValidationError(PipelineError):
    """Raised when a storyboard is malformed, missing scenes, or violates duration bounds."""

    pass


from src.storyboard_generator.exceptions import ScriptFidelityError



class MissingSceneImageError(PipelineError):
    """Raised when one or more storyboard scenes lack valid production images (Gate C)."""

    pass


class MockAssetQuarantineError(PipelineError):
    """Raised when a mock image, mock audio, or mock asset attempts to enter production rendering."""

    pass


class MissingAudioAssetError(PipelineError):
    """Raised when required audio assets (voiceover, BGM) are missing or inaudible (Gate D)."""

    pass


class AudioSynthesisError(PipelineError):
    """Raised when voiceover TTS synthesis fails or generates empty audio."""

    pass


class CaptionGenerationError(PipelineError):
    """Raised when subtitle extraction, parsing, or export fails."""

    pass


class VideoRenderingError(PipelineError):
    """Raised when FFmpeg video composition or encoding fails."""

    pass


class QualityGateError(PipelineError):
    """Raised when quality checks fail or incomplete inspections block upload eligibility (Gate E)."""

    pass


class HumanApprovalRequiredError(PipelineError):
    """Raised when an action requires explicit human approval sign-off that is missing or expired (Gate F)."""

    pass


class UploadDisabledError(PipelineError):
    """Raised when an upload attempt is made while uploads are intentionally disabled."""

    pass


class PipelineRecoveryError(PipelineError):
    """Raised when production state recovery or checkpoint resumption fails."""

    pass


class ConcurrentPipelineExecutionError(PipelineError):
    """Raised when concurrent pipeline execution is attempted for an active production."""

    pass
