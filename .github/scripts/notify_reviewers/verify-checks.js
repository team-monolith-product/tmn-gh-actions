/**
 * Verify required GitHub checks have passed
 * - If any check has failed, abort immediately
 * - If any check is still running, skip (will be triggered again by workflow_run)
 *
 * Environment variables:
 * - REQUIRED_CHECKS: JSON array of check names to verify
 * - PR_SHA: The commit SHA to check
 *
 * @param {object} github - GitHub API client
 * @param {object} context - GitHub Actions context
 * @param {object} core - GitHub Actions core utilities
 */
module.exports = async ({ github, context, core }) => {
  const requiredChecks = JSON.parse(process.env.REQUIRED_CHECKS);
  const prSha = process.env.PR_SHA;

  if (requiredChecks.length === 0) {
    console.log('No required checks specified. Skipping check verification.');
    return;
  }

  console.log(`Verifying checks: ${requiredChecks.join(', ')}`);

  const { data: checkRuns } = await github.rest.checks.listForRef({
    owner: context.repo.owner,
    repo: context.repo.repo,
    ref: prSha,
  });

  const relevantChecks = checkRuns.check_runs.filter(check =>
    requiredChecks.includes(check.name)
  );

  console.log(`Found ${relevantChecks.length}/${requiredChecks.length} required checks`);

  for (const checkName of requiredChecks) {
    const check = relevantChecks.find(c => c.name === checkName);

    if (!check) {
      console.log(`Check "${checkName}" not found yet. Skipping notification.`);
      core.setFailed(`Check "${checkName}" not found`);
      return;
    }

    if (check.status !== 'completed') {
      console.log(`Check "${checkName}" is still running. Skipping notification.`);
      core.setFailed(`Check "${checkName}" is still running`);
      return;
    }

    if (check.conclusion === 'failure' || check.conclusion === 'cancelled') {
      console.log(`Check "${checkName}" failed (${check.conclusion}). Aborting.`);
      core.setFailed(`Check "${checkName}" failed`);
      return;
    }

    console.log(`Check "${checkName}": ${check.conclusion}`);
  }

  console.log('All required checks passed!');
};
