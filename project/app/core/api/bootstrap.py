"""bootstrap — assemble the core/api layer from built services (ADR-0009).

``build_api_layer`` wires one :class:`EventBus` and the facades over the services
that ``main.py`` already constructs, and returns them in an :class:`ApiLayer`.
The named-pipe ``adapters/ipc`` channel and the constrained browser-local
adapter drive this exact object — one facade set, interchangeable input
adapters. The browser adapter remains read-only and maps its own opaque IDs;
it never exposes the named-pipe router.

The heavier "build the whole recording stack headless, by role" belongs to the
daemon entrypoint (M4); this module takes already-built services so adopting it
introduces zero behaviour change to the running app.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.core.api import dto
from app.core.api.clips_api import ClipsApi
from app.core.api.delivery_api import DeliveryApi
from app.core.api.editor_api import EditorApi
from app.core.api.events import EventBus
from app.core.api.recording_api import RecordingApi
from app.core.api.requests_api import RequestsApi
from app.core.api.settings_api import SettingsApi
from app.core.cloud_share_service import CloudShareService
from app.core.event_service import EventService
from app.core.monitor_detection.service import MonitorDetectionService
from app.core.player.player_service import PlayerService
from app.core.ports.analytics_query_port import AnalyticsQueryPort
from app.core.ports.audit_port import AuditPort
from app.core.ports.clip_inspector_port import ClipInspectorPort
from app.core.ports.editor_export_port import EditorExportPort
from app.core.ports.file_browser_port import FileBrowserPort
from app.core.ports.mp4_converter_port import Mp4ConverterPort
from app.core.ports.preview_server_port import PreviewServerPort
from app.core.ports.user_config_port import UserConfigPort
from app.core.recording_service.service import RecordingService
from app.infrastructure.config import Settings


@dataclass
class ApiLayer:
    """The wired input port — everything an entry adapter needs, and nothing Qt."""

    bus: EventBus
    recording: RecordingApi
    settings: SettingsApi
    editor: EditorApi
    clips: ClipsApi
    requests: RequestsApi
    delivery: DeliveryApi
    analytics: Optional[AnalyticsQueryPort] = None
    preview_server: Optional[PreviewServerPort] = None

    def start(self) -> None:
        self.bus.start()

    def stop(self) -> None:
        self.bus.stop()


def build_api_layer(
    *,
    detection_service: MonitorDetectionService,
    settings: Settings,
    user_config_port: UserConfigPort,
    audit_port: Optional[AuditPort] = None,
    recording_service: Optional[RecordingService] = None,
    event_service: Optional[EventService] = None,
    player_service: Optional[PlayerService] = None,
    export_port: Optional[EditorExportPort] = None,
    inspector: Optional[ClipInspectorPort] = None,
    file_browser: Optional[FileBrowserPort] = None,
    mp4_converter: Optional[Mp4ConverterPort] = None,
    cloud_share_service: Optional[CloudShareService] = None,
    clips_dir: Optional[Path] = None,
    event_clips_dir: Optional[Path] = None,
    slc_storage_host: str = "",
    onedrive_base_folder: str = "SLC/clips-supervisor",
    relaunch_cb: Optional[Callable[[], None]] = None,
    autorecord_cb: Optional[Callable[[bool], None]] = None,
    analytics_query: Optional[AnalyticsQueryPort] = None,
    preview_server: Optional[PreviewServerPort] = None,
    start_bus: bool = False,
) -> ApiLayer:
    """Assemble the EventBus + all facades over the given services.

    ``recording_service`` / ``event_service`` are ``None`` on non-recording roles
    (supervisor / unconfigured) — the facades degrade gracefully.
    """
    bus = EventBus()

    editor = EditorApi(
        event_bus=bus,
        export_port=export_port,
        clips_dir=clips_dir,
        inspector=inspector,
    )

    layer = ApiLayer(
        bus=bus,
        recording=RecordingApi(
            event_bus=bus,
            detection_service=detection_service,
            recording_service=recording_service,
            event_service=event_service,
            user_config_port=user_config_port,
            audit_port=audit_port,
            preview_server=preview_server,
        ),
        settings=SettingsApi(
            event_bus=bus,
            user_config_port=user_config_port,
            settings=settings,
            audit_port=audit_port,
            relaunch_cb=relaunch_cb,
            autorecord_cb=autorecord_cb,
        ),
        editor=editor,
        clips=ClipsApi(
            event_bus=bus,
            clips_dir=clips_dir or Path("."),
            event_clips_dir=event_clips_dir,
            player_service=player_service,
            file_browser=file_browser,
            mp4_converter=mp4_converter,
        ),
        requests=RequestsApi(
            event_bus=bus,
            file_browser=file_browser,
            slc_storage_host=slc_storage_host,
        ),
        delivery=DeliveryApi(
            event_bus=bus,
            cloud_share_service=cloud_share_service,
            onedrive_base_folder=onedrive_base_folder,
            export_fn=lambda p: editor.export_timeline(dto.ExportTimeline(output_path=p)),
            is_exporting=lambda: editor.exporting,
        ),
        analytics=analytics_query,
    )
    if start_bus:
        layer.start()
    return layer
