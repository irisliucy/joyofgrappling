from typing import Literal, Optional

from pydantic import BaseModel, Field

Source = Literal["youtube", "bilibili", "meta"]

TransitionType = Literal[
    "finish", "sweep", "back_take", "escape", "pass", "entry", "counter", "re_counter"
]

NodeCategory = Literal[
    "guard", "submission", "top_control", "back_control", "mount",
    "leglock", "transition", "takedown",
]

ConfidenceLabel = Literal["established", "emerging", "contested", "signature", "unverified"]

Ruleset = Literal["nogi", "gi", "mma", "unknown"]


class VideoMeta(BaseModel):
    video_id: str
    title: str
    channel_id: str
    channel_name: str
    published_at: str
    duration_seconds: int = 0
    view_count: int = 0
    description: str = ""
    url: str
    source: Source = "youtube"


class CaptionSegment(BaseModel):
    start_seconds: float
    end_seconds: float
    text: str


class Caption(BaseModel):
    video_id: str
    language: str
    segments: list[CaptionSegment]


class SourceScore(BaseModel):
    channel_id: str
    authority_tier: int = 4
    is_competition_footage: bool = False
    instructor_identity: Optional[str] = None
    lineage: Optional[str] = None
    ruleset: Ruleset = "unknown"
    notes: str = ""


class RawExtraction(BaseModel):
    from_position: str
    to_position: str
    transition_type: TransitionType
    condition: Optional[str] = None
    grip_detail: Optional[str] = None
    body_cue: Optional[str] = None
    timestamp_start: float = 0
    confidence: Literal["high", "medium", "low"] = "medium"
    needs_review: bool = False
    raw_quote: str = ""


class SourceRef(BaseModel):
    video_id: str
    video_url: str
    channel_name: str
    authority_tier: int
    is_competition_footage: bool
    timestamp_start: float
    raw_quote: str


class InsightEdge(BaseModel):
    id: str
    from_position: str
    to_position: str
    transition_type: TransitionType
    conditions: list[str] = Field(default_factory=list)
    grip_details: list[str] = Field(default_factory=list)
    body_cues: list[str] = Field(default_factory=list)
    source_count: int = 0
    sources: list[SourceRef] = Field(default_factory=list)
    highest_authority_tier: int = 4
    has_competition_footage: bool = False
    confidence_label: ConfidenceLabel = "unverified"
    contested: bool = False
    contested_detail: Optional[str] = None
    first_seen: str = ""
    last_seen: str = ""
    temporal_signal: Literal["rising", "stable", "declining", "insufficient_data"] = "insufficient_data"


class LoopDecision(BaseModel):
    should_continue: bool
    reason: str
    new_nodes_this_iteration: int
    new_edges_this_iteration: int
    novelty_rate: float


class GraphNode(BaseModel):
    id: str
    label: str
    category: NodeCategory
    mention_count: int = 0
    source_count: int = 0


EdgeStage = Literal["entry", "transition", "result"]

# entry: how you get into the position. transition: solving a problem
# (opponent's counter, escape, defense) en route. result: an outcome that
# produces control -- submission, sweep, back take, or guard pass.
TRANSITION_TYPE_STAGE: dict[str, EdgeStage] = {
    "entry": "entry",
    "counter": "transition",
    "re_counter": "transition",
    "escape": "transition",
    "finish": "result",
    "sweep": "result",
    "back_take": "result",
    "pass": "result",
}


class GraphEdge(BaseModel):
    id: str
    from_: str = Field(alias="from")
    to: str
    transition_type: TransitionType
    stage: EdgeStage
    weight: int
    confidence_label: ConfidenceLabel
    has_competition_footage: bool

    model_config = {"populate_by_name": True}


class TechniqueGraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class InsightSummary(BaseModel):
    text: str
    confidence_label: ConfidenceLabel
    source_count: int
    supporting_video_ids: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)  # timestamped, for click-to-play
    graph_edge_id: str = ""    # matches GraphEdge.id, for hover-highlight
    from_node_id: str = ""     # matches GraphNode.id
    to_node_id: str = ""       # matches GraphNode.id


class ContestedDetail(BaseModel):
    technique: str
    point_of_disagreement: str
    side_a: str
    side_b: str
    side_a_sources: list[str] = Field(default_factory=list)
    side_b_sources: list[str] = Field(default_factory=list)


class ReapOutput(BaseModel):
    query: str
    generated_at: str
    iteration_count: int
    videos_processed: int
    graph: TechniqueGraph
    insights: list[InsightSummary] = Field(default_factory=list)
    contested: list[ContestedDetail] = Field(default_factory=list)
    sources_used: list[SourceRef] = Field(default_factory=list)


class ReapConfig(BaseModel):
    query: str
    max_iterations: int = 8
    top_videos_per_iteration: int = 5
    novelty_threshold: float = 0.10
    max_edges: int = 200
    ruleset: Literal["nogi", "gi", "both"] = "nogi"
    include_competition_search: bool = True
    language: str = "en"
    target_player: Optional[str] = None
