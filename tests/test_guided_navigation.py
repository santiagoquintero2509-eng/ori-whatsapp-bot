import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import server


class GuidedNavigationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.memory = {"history": [{"user": "hola"}], "guided_mode": "main"}
        self.stack.enter_context(patch.object(server, "get_memory", return_value=self.memory))
        self.admin = self.stack.enter_context(
            patch.object(server, "is_admin_session_active", return_value=False)
        )
        self.mocks = {}
        for name in (
            "log_incoming_message", "remember_menu_turn", "mark_welcome_buttons_sent",
            "send_initial_welcome", "send_whatsapp_buttons", "send_whatsapp_list",
            "send_whatsapp_text", "send_whatsapp_image", "save_persistent_state",
            "get_ori_reply", "transcribe_incoming_audio", "send_admin_menu",
            "send_preinscription_category_list_if_needed",
            "send_preinscription_confirmation_buttons_if_needed",
        ):
            self.mocks[name] = self.stack.enter_context(patch.object(server, name))
        for name, value in (
            ("is_message_for_configured_phone_number", True),
            ("is_duplicate_incoming_message", False),
            ("should_send_plan_image", False),
            ("should_send_previous_fair_images", False),
            ("is_admin_pdf_request", False),
        ):
            self.stack.enter_context(patch.object(server, name, return_value=value))
        self.mocks["get_ori_reply"].return_value = "Respuesta"

    def dispatch(self, kind="text", text="consulta libre", **extra):
        message = {"from": "test-user", "type": kind, "text": text, **extra}
        with patch.object(server, "extract_incoming_messages", return_value=[message]):
            server.handle_whatsapp_payload({})

    def test_free_messages_return_the_correct_menu_without_ai_or_transcription(self):
        for mode in ("main", "expositor", "visitante"):
            for kind in ("text", "audio", "image", "document", "interactive"):
                with self.subTest(mode=mode, kind=kind):
                    self.memory["guided_mode"] = mode
                    self.dispatch(kind)
                    sender = self.mocks[
                        "send_whatsapp_buttons" if mode == "main" else "send_whatsapp_list"
                    ]
                    self.assertEqual(
                        sender.call_args.args[1],
                        "Para continuar, selecciona una de las opciones que aparecen abajo.",
                    )
        self.mocks["get_ori_reply"].assert_not_called()
        self.mocks["transcribe_incoming_audio"].assert_not_called()

    def test_first_message_keeps_the_welcome(self):
        self.memory.clear()
        self.dispatch(text="Hola")
        self.mocks["send_initial_welcome"].assert_called_once_with("test-user")
        self.mocks["get_ori_reply"].assert_not_called()

    def test_returning_greeting_is_friendly_and_includes_navigation_instruction(self):
        self.dispatch(text="Hola")
        body = self.mocks["send_whatsapp_buttons"].call_args.args[1]
        self.assertIn("Hola de nuevo", body)
        self.assertIn("selecciona una de las opciones", body)

    def test_valid_buttons_are_handled_before_the_gate(self):
        self.dispatch("interactive", button_id="ORI_MENU")
        self.mocks["send_whatsapp_buttons"].assert_called_once_with(
            "test-user", server.MAIN_MENU_TEXT, server.MAIN_MENU_BUTTONS
        )
        self.mocks["get_ori_reply"].assert_not_called()

    def test_questionnaire_accepts_data_and_files(self):
        self.memory["preinscription"] = {"active": True, "step": "files"}
        for kind in ("text", "image", "document"):
            self.dispatch(kind)
        self.assertEqual(self.mocks["get_ori_reply"].call_count, 3)

    def test_post_submission_corrections_accept_text(self):
        self.memory["pending_field"] = "post_submission_correction"
        self.dispatch()
        self.mocks["get_ori_reply"].assert_called_once()

    def test_admin_commands_and_sessions_bypass_gate(self):
        self.memory.clear()
        self.dispatch(text="In_adm1n")
        self.dispatch(text="Out_adm1n")
        self.admin.return_value = True
        self.dispatch(text="consultar preinscritos")
        self.assertEqual(self.mocks["get_ori_reply"].call_count, 3)
        self.mocks["send_initial_welcome"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
