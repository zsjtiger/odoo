# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAIAgentConfig(TransactionCase):
    """The configuration an agent keeps about itself: skills, prompt, avatar and previews."""

    def setUp(self):
        super().setUp()
        self.agent = self.env["ai.agent"].create({"name": "Config Agent", "system_prompt": "Do this"})
        self.self_update_skill = self.env.ref("ai_agentic.ai_skill_self_update")

    def test_custom_skills_exclude_native_skills(self):
        """Custom skills only list the user-made skills, and editing them keeps the native ones."""
        custom_skill = self.env["ai.skill"].create({"name": "Custom Skill", "instructions": "Do it"})
        self.agent.skill_ids = self.self_update_skill | custom_skill
        self.assertTrue(self.self_update_skill.is_native_skill)
        self.assertEqual(self.agent.custom_skill_ids, custom_skill)

        self.agent.custom_skill_ids = self.env["ai.skill"]
        self.assertEqual(self.agent.skill_ids, self.self_update_skill)

    def test_escaped_newlines_in_system_prompt_are_restored(self):
        """A prompt the LLM sent with escaped newlines is stored with real line breaks."""
        self.agent.write({"system_prompt": "Line one\\nLine two\\r\\nLine three"})
        self.assertEqual(self.agent.system_prompt, "Line one\nLine two\nLine three")

    def test_prompt_with_real_newlines_is_kept(self):
        """A prompt that already has line breaks is stored untouched, even with a literal backslash-n."""
        self.agent.write({"system_prompt": "Line one\nKeep \\n literally"})
        self.assertEqual(self.agent.system_prompt, "Line one\nKeep \\n literally")

    def test_setup_protocol_only_for_blank_agents(self):
        """The setup protocol is only shown when the agent has the Self Update skill and no instructions."""
        self.agent.skill_ids = self.self_update_skill
        self.assertEqual(self.agent._get_setup_protocol(), "")
        self.agent.system_prompt = ""
        self.assertTrue(self.agent._get_setup_protocol())

    def test_avatar_role_redraws_avatar_with_new_role(self):
        """Changing the avatar role keeps the color of the avatar and changes its depicted role."""
        self.agent.avatar_role = "Worker"
        self.assertEqual(self.agent.avatar_role, "Worker")
        self.agent.avatar_role = "Artist"
        self.assertEqual(self.agent.avatar_role, "Artist")
        self.assertTrue(self.agent._avatar_attachment().name.endswith("-Artist"))

    def test_preview_links_hide_agent_self_updates(self):
        """A self-update of the agent is announced by a single link, not as a record preview."""
        links = self.env["ai.tool"]._get_preview_links("write", {"ai.agent": self.agent})
        self.assertEqual(len(links), 1)
        self.assertIn("self-updated its configuration", str(links[0]))
