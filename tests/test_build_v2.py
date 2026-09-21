import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/build_v2.yml"
DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64
VALUES = "static-nginx/aws-apne2-dev-service.yaml"


class BuildV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads(
            subprocess.check_output(["yq", "-o=json", str(WORKFLOW)], text=True)
        )
        steps = cls.workflow["jobs"]["update-tag"]["steps"]
        cls.changes_script = next(step["run"] for step in steps if step.get("id") == "changes")
        cls.update_script = next(
            step["with"]["cmd"]
            for step in steps
            if step["name"] == "Update Helm values and push"
        )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.git = shutil.which("git")
        self.env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": str(self.root / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
            "GIT_TERMINAL_PROMPT": "0",
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "REAL_GIT": self.git,
            "PUSH_LOG": str(self.root / "push.log"),
        }
        self.write_executable("apk", "#!/bin/sh\nexit 0\n")
        self.write_executable(
            "git",
            """#!/bin/sh
if [ "$1" = push ]; then
  printf 'push\n' >> "$PUSH_LOG"
  if [ -n "${CONCURRENT_REPO:-}" ] && [ ! -f "$PUSH_LOG.race" ]; then
    touch "$PUSH_LOG.race"
    "$REAL_GIT" -C "$CONCURRENT_REPO" push origin HEAD:refs/heads/main || exit 1
  fi
fi
exec "$REAL_GIT" "$@"
""",
        )
        self.remote = self.root / "remote.git"
        self.checkout = self.root / "helm"
        self.run_git("init", "--bare", "--initial-branch=main", str(self.remote))
        self.run_git("clone", str(self.remote), str(self.checkout))
        value_file = self.checkout / VALUES
        value_file.parent.mkdir()
        value_file.write_text(
            """defaults: &defaults
  pullPolicy: IfNotPresent
sites:
  contentsHtml:
    image:
      <<: *defaults
      tag: old
      digest: previous
  secondSite:
    image:
      tag: other-old
      digest: other-previous
"""
        )
        self.run_git("add", ".", cwd=self.checkout)
        self.run_git("commit", "-m", "Initial values", cwd=self.checkout)
        self.run_git("push", "origin", "main", cwd=self.checkout)
        self.initial = self.run_git("rev-parse", "HEAD", cwd=self.checkout).stdout.strip()

    def write_executable(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def run_git(self, *args, cwd=None, check=True):
        return subprocess.run(
            [self.git, *args], cwd=cwd or self.root, env=self.env,
            text=True, capture_output=True, check=check,
        )

    def make_changes(self, digest_path="sites.contentsHtml.image.digest", digest=DIGEST):
        (self.root / "updateTargets.json").write_text(json.dumps({
            "aws": {"imageName": "assets", "valueFilePath": [VALUES, None, "null"]}
        }))
        output = self.root / "output"
        result = subprocess.run(
            ["bash", "-eu", "-c", self.changes_script], cwd=self.root,
            env={**self.env, "PROPERTY_PATH": "sites.contentsHtml.image.tag",
                 "DIGEST_PROPERTY_PATH": digest_path, "IMAGE_TAG": "release-123",
                 "IMAGE_DIGEST": digest, "GITHUB_OUTPUT": str(output)},
            text=True, capture_output=True,
        )
        changes = None
        if result.returncode == 0:
            changes = json.loads(output.read_text().split("changes=", 1)[1])
        return result, changes

    def publish(self, changes, **env):
        return subprocess.run(
            ["sh", "-c", self.update_script], cwd=self.root,
            env={**self.env, "HELM_REPOSITORY": str(self.checkout), "TARGET": "main",
                 "IMAGE_TAG": "release-123", "CHANGES": json.dumps(changes), **env},
            text=True, capture_output=True,
        )

    def remote_values(self):
        content = self.run_git("--git-dir", str(self.remote), "show", f"main:{VALUES}").stdout
        parsed = subprocess.check_output(["yq", "-o=json"], input=content, text=True)
        return content, json.loads(parsed)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_workflow_digest_output_and_opt_in_contract(self):
        call = self.workflow["on"]["workflow_call"]
        self.assertEqual(call["inputs"]["propertyPath"]["default"], "image.tag")
        self.assertFalse(call["inputs"]["digestPropertyPath"]["required"])
        self.assertEqual(call["inputs"]["digestPropertyPath"]["default"], "")
        self.assertEqual(call["outputs"]["digest"]["value"], "${{ jobs.build-image.outputs.digest }}")
        build = self.workflow["jobs"]["build-image"]
        self.assertEqual(build["outputs"]["digest"], "${{ steps.build-push.outputs.digest }}")
        push = next(step for step in build["steps"] if step.get("id") == "build-push")
        self.assertTrue(push["uses"].startswith("docker/build-push-action@"))
        self.assertTrue(push["with"]["push"])

    def test_tag_and_digest_update_in_one_commit_preserving_yaml_merge(self):
        result, changes = self.make_changes()
        self.assert_success(result)
        self.assert_success(self.publish(changes))
        content, values = self.remote_values()
        image = values["sites"]["contentsHtml"]["image"]
        self.assertEqual(image["tag"], "release-123")
        self.assertEqual(image["digest"], DIGEST)
        self.assertEqual(values["sites"]["secondSite"]["image"]["tag"], "other-old")
        self.assertIn("<<: *defaults", content)
        commits = self.run_git("--git-dir", str(self.remote), "rev-list", "--count", f"{self.initial}..main")
        self.assertEqual(commits.stdout.strip(), "1")
        self.assertEqual(self.run_git("status", "--porcelain", cwd=self.checkout).stdout, "")

    def test_opt_out_preserves_existing_digest(self):
        result, changes = self.make_changes(digest_path="", digest="")
        self.assert_success(result)
        self.assertEqual(changes, {VALUES: {"sites.contentsHtml.image.tag": "release-123"}})
        self.assert_success(self.publish(changes))
        _, values = self.remote_values()
        self.assertEqual(values["sites"]["contentsHtml"]["image"]["digest"], "previous")

    def test_invalid_digest_fails_before_helm_write(self):
        for digest in ("", "sha256:short", "not-a-digest"):
            with self.subTest(digest=digest):
                result, changes = self.make_changes(digest=digest)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(changes)
        self.assertEqual(self.run_git("--git-dir", str(self.remote), "rev-parse", "main").stdout.strip(), self.initial)

    def test_same_tag_and_digest_path_fails(self):
        result, _ = self.make_changes(digest_path="sites.contentsHtml.image.tag")
        self.assertNotEqual(result.returncode, 0)

    def test_concurrent_same_file_update_is_preserved_on_retry(self):
        concurrent = self.root / "concurrent"
        self.run_git("clone", str(self.remote), str(concurrent))
        path = concurrent / VALUES
        path.write_text(path.read_text().replace("other-old", "other-new").replace("other-previous", OTHER_DIGEST))
        self.run_git("add", VALUES, cwd=concurrent)
        self.run_git("commit", "-m", "Update another site", cwd=concurrent)
        other_commit = self.run_git("rev-parse", "HEAD", cwd=concurrent).stdout.strip()
        result, changes = self.make_changes()
        self.assert_success(result)
        self.assert_success(self.publish(changes, CONCURRENT_REPO=str(concurrent)))
        _, values = self.remote_values()
        self.assertEqual(values["sites"]["contentsHtml"]["image"]["digest"], DIGEST)
        self.assertEqual(values["sites"]["secondSite"]["image"], {"tag": "other-new", "digest": OTHER_DIGEST})
        self.assertEqual((self.root / "push.log").read_text().splitlines(), ["push", "push"])
        parent = self.run_git("--git-dir", str(self.remote), "rev-parse", "main^").stdout.strip()
        self.assertEqual(parent, other_commit)

    def test_repeated_push_failure_stops_after_three_attempts(self):
        hook = self.remote / "hooks/pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        result, changes = self.make_changes()
        self.assert_success(result)
        result = self.publish(changes)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / "push.log").read_text().splitlines(), ["push"] * 3)
        self.assertEqual(self.run_git("--git-dir", str(self.remote), "rev-parse", "main").stdout.strip(), self.initial)
        self.assertEqual(self.run_git("worktree", "list", "--porcelain", cwd=self.checkout).stdout.count("worktree "), 1)

    def test_repeated_publish_is_a_no_op(self):
        result, changes = self.make_changes()
        self.assert_success(result)
        self.assert_success(self.publish(changes))
        self.assert_success(self.publish(changes))
        self.assertEqual((self.root / "push.log").read_text().splitlines(), ["push"])

    def test_mutation_failure_does_not_publish_partial_values(self):
        result, changes = self.make_changes()
        self.assert_success(result)
        changes["missing.yaml"] = {"image.tag": "release-123"}
        self.assertNotEqual(self.publish(changes).returncode, 0)
        self.assertEqual(self.run_git("--git-dir", str(self.remote), "rev-parse", "main").stdout.strip(), self.initial)
        self.assertFalse((self.root / "push.log").exists())
        self.assertEqual(self.run_git("worktree", "list", "--porcelain", cwd=self.checkout).stdout.count("worktree "), 1)


if __name__ == "__main__":
    unittest.main()
