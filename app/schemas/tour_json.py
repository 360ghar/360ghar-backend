from pydantic import BaseModel, Field


class InitialViewSchema(BaseModel):
    yaw: float = 0.0
    pitch: float = 0.0
    zoom: float = 50.0

class SceneMetadataSchema(BaseModel):
    initial_view: InitialViewSchema
    room_type: str | None = None
    caption: str | None = None
    narration_script: str | None = None

class HotspotPositionSchema(BaseModel):
    yaw: float
    pitch: float
    radius: float | None = None

class HotspotSchema(BaseModel):
    id: str
    type: str = "navigation"
    target_scene_id: str
    title: str
    position: HotspotPositionSchema
    order_index: int = 0

class SceneSchema(BaseModel):
    id: str
    image_key: str | None = None
    room_type: str | None = None
    title: str
    description: str | None = None
    caption: str | None = None
    narration_script: str | None = None
    order_index: int = 0
    metadata: SceneMetadataSchema | None = None
    hotspots: list[HotspotSchema] = Field(default_factory=list)

class TourJsonSchema(BaseModel):
    title: str
    generator: str | None = None
    initial_scene_id: str
    scenes: list[SceneSchema] = Field(default_factory=list)
