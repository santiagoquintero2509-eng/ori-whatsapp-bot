import io
import json
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import dynamic_plan
import server
from PIL import Image, ImageDraw


class PlanRenderingTests(unittest.TestCase):
    def test_public_plan_draws_all_64_numbers_without_reading_sheet(self):
        with patch.object(dynamic_plan, "filter_form_records") as sheet:
            with patch.object(ImageDraw.ImageDraw, "text", autospec=True) as draw_text:
                media = dynamic_plan.numbered_plan_media()
        sheet.assert_not_called()
        labels = {call.args[2] for call in draw_text.call_args_list}
        self.assertEqual(labels, {f"{number:02d}" for number in range(1, 65)})
        self.assertEqual(Image.open(io.BytesIO(media["content"])).format, "JPEG")

    def test_admin_plan_still_uses_live_confirmations(self):
        with patch.object(dynamic_plan, "filter_form_records", return_value=[
            {"confirmed_stand": "01, 64"}
        ]) as sheet:
            with patch.object(ImageDraw.ImageDraw, "text", autospec=True) as draw_text:
                dynamic_plan.dynamic_plan_media()
        sheet.assert_called_once_with(force=True)
        labels = {call.args[2] for call in draw_text.call_args_list}
        self.assertEqual(labels, {f"{number:02d}" for number in range(2, 64)})


class PlanDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key, value in {"DRY_RUN": False, "WHATSAPP_TOKEN": "test", "PHONE_NUMBER_ID": "test"}.items():
            self.stack.enter_context(patch.object(server, key, value))
        self.public_media = {"filename": "numbered.jpg", "content": b"public", "mime_type": "image/jpeg"}
        self.live_media = {"filename": "live.jpg", "content": b"admin", "mime_type": "image/jpeg"}
        self.public = self.stack.enter_context(patch.object(server, "numbered_plan_media", return_value=self.public_media))
        self.live = self.stack.enter_context(patch.object(server, "dynamic_plan_media", return_value=self.live_media))
        self.admin = self.stack.enter_context(patch.object(server, "is_admin_session_active", return_value=False))
        self.upload = self.stack.enter_context(patch.object(server, "upload_whatsapp_media", return_value="media-id"))
        self.network = self.stack.enter_context(patch.object(server.urllib.request, "urlopen"))
        self.stack.enter_context(patch.object(server, "log_outgoing_message"))
        self.notify = self.stack.enter_context(patch.object(server, "send_whatsapp_text"))

    def test_public_recipient_gets_numbered_media(self):
        server.send_whatsapp_image("visitor", server.PLANO_STANDS_URL)
        self.live.assert_not_called()
        self.upload.assert_called_once_with(self.public_media)
        payload = json.loads(self.network.call_args.args[0].data)
        self.assertEqual(payload["image"], {"id": "media-id"})

    def test_admin_recipient_gets_live_media(self):
        self.admin.return_value = True
        server.send_whatsapp_image("admin", server.PLANO_STANDS_URL)
        self.public.assert_not_called()
        self.upload.assert_called_once_with(self.live_media)

    def test_custom_configured_plan_url_cannot_bypass_public_selection(self):
        with patch.object(server, "PLANO_STANDS_URL", "https://example.com/old-live-plan.png"):
            server.send_whatsapp_image("visitor", server.PLANO_STANDS_URL)
        self.upload.assert_called_once_with(self.public_media)
        self.live.assert_not_called()

    def test_public_http_endpoint_never_serves_dynamic_plan(self):
        handler = Mock(path="/plano_stands.jpg?refresh=1")
        server.OriHandler.do_GET(handler)
        self.live.assert_not_called()
        handler.send_binary.assert_called_once_with(
            b"public", "image/jpeg", "numbered.jpg", cache_control="no-store, max-age=0"
        )

    def test_upload_failure_does_not_fall_back_to_another_plan(self):
        for is_admin in (False, True):
            with self.subTest(is_admin=is_admin):
                self.admin.return_value = is_admin
                self.upload.side_effect = RuntimeError("upload unavailable")
                server.send_whatsapp_image("recipient", server.PLANO_STANDS_URL)
        self.network.assert_not_called()
        self.assertEqual(self.notify.call_count, 2)

    def test_missing_public_plan_does_not_fall_back_to_old_availability(self):
        self.public.return_value = None
        server.send_whatsapp_image("visitor", server.PLANO_STANDS_URL)
        self.upload.assert_not_called()
        self.network.assert_not_called()
        self.live.assert_not_called()
        handler = Mock(path="/plano_stands.jpg")
        server.OriHandler.do_GET(handler)
        self.assertEqual(handler.send_json.call_args.kwargs["status"], 503)


if __name__ == "__main__":
    unittest.main()
