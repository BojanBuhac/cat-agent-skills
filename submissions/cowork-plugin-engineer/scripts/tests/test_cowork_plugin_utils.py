import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import cowork_plugin_utils


class RunAtkSecurityTests(unittest.TestCase):
    def test_run_atk_uses_isolated_workspace_and_fixed_package(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / ".npmrc").write_text(
                "@microsoft:registry=https://attacker.example/\n",
                encoding="utf-8",
            )
            malicious_package = (
                project
                / "node_modules"
                / "@microsoft"
                / "m365agentstoolkit-cli"
            )
            malicious_package.mkdir(parents=True)

            with (
                mock.patch.object(
                    cowork_plugin_utils,
                    "find_npx_command",
                    return_value=(["trusted-npx"], os.defpath),
                ),
                mock.patch.object(
                    cowork_plugin_utils.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0),
                ) as run,
            ):
                cowork_plugin_utils.run_atk(
                    ["validate", "--package-file", str(project / "plugin.zip")],
                    excluded_roots=(project,),
                )

        command = run.call_args.args[0]
        invocation = run.call_args.kwargs
        self.assertEqual(
            command[:6],
            [
                "trusted-npx",
                "--yes",
                "--ignore-scripts",
                "--package=@microsoft/m365agentstoolkit-cli@1.1.15",
                "--",
                "atk",
            ],
        )
        self.assertNotEqual(invocation["cwd"], project)
        self.assertFalse(
            cowork_plugin_utils._is_within(invocation["cwd"], (project,))
        )
        self.assertFalse(invocation["shell"])

    def test_run_atk_replaces_dangerous_environment_settings(self):
        hostile_environment = {
            "PATH": os.defpath,
            "NPM_CONFIG_REGISTRY": "https://attacker.example/",
            "npm_config_userconfig": "attacker.npmrc",
            "NODE_OPTIONS": "--require=attacker.js",
            "NODE_PATH": "attacker-modules",
            "INIT_CWD": "attacker-project",
        }
        with (
            mock.patch.dict(os.environ, hostile_environment, clear=True),
            mock.patch.object(
                cowork_plugin_utils,
                "find_npx_command",
                return_value=(["trusted-npx"], os.defpath),
            ),
            mock.patch.object(
                cowork_plugin_utils.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0),
            ) as run,
        ):
            cowork_plugin_utils.run_atk(["validate"])

        environment = run.call_args.kwargs["env"]
        self.assertEqual(
            environment["NPM_CONFIG_REGISTRY"],
            "https://registry.npmjs.org/",
        )
        self.assertEqual(environment["NPM_CONFIG_IGNORE_SCRIPTS"], "true")
        self.assertNotIn("npm_config_userconfig", environment)
        self.assertNotIn("NODE_OPTIONS", environment)
        self.assertNotIn("NODE_PATH", environment)
        self.assertNotIn("INIT_CWD", environment)

    def test_safe_path_directories_reject_untrusted_and_relative_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trusted = root / "trusted"
            project = root / "project"
            trusted.mkdir()
            project.mkdir()
            path_value = os.pathsep.join(
                ("", ".", "relative-bin", str(project), str(trusted))
            )
            with mock.patch.dict(os.environ, {"PATH": path_value}, clear=True):
                result = cowork_plugin_utils._safe_path_directories((project,))

        self.assertEqual(result, [trusted.resolve()])

    def test_atk_registry_requires_safe_https_url(self):
        invalid = (
            "http://registry.example/",
            "https://user:secret@registry.example/",
            "https://registry.example/?source=other",
            "https://registry.example/#fragment",
        )
        for registry in invalid:
            with (
                self.subTest(registry=registry),
                mock.patch.dict(
                    os.environ,
                    {"COWORK_ATK_REGISTRY": registry},
                    clear=True,
                ),
                self.assertRaises(cowork_plugin_utils.CoworkPluginError),
            ):
                cowork_plugin_utils._atk_registry()

        with mock.patch.dict(
            os.environ,
            {"COWORK_ATK_REGISTRY": "https://packages.example/npm"},
            clear=True,
        ):
            self.assertEqual(
                cowork_plugin_utils._atk_registry(),
                "https://packages.example/npm/",
            )


if __name__ == "__main__":
    unittest.main()
