/**
 * Wait for required GitHub checks to complete
 *
 * Environment variables:
 * - REQUIRED_CHECKS: JSON array of check names to wait for
 *
 * @param {object} github - GitHub API client
 * @param {object} context - GitHub Actions context
 * @param {object} core - GitHub Actions core utilities
 */
module.exports = async ({ github, context, core }) => {
  const requiredChecks = JSON.parse(process.env.REQUIRED_CHECKS);

  if (requiredChecks.length === 0) {
    console.log('No required checks specified. Skipping check verification.');
    return;
  }

  console.log(`Waiting for checks: ${requiredChecks.join(', ')}`);

  while (true) {
    const { data: checkRuns } = await github.rest.checks.listForRef({
      owner: context.repo.owner,
      repo: context.repo.repo,
      ref: context.payload.pull_request.head.sha,
    });

    const relevantChecks = checkRuns.check_runs.filter(check =>
      requiredChecks.includes(check.name)
    );

    console.log(`Found ${relevantChecks.length}/${requiredChecks.length} required checks`);

    const allCompleted = requiredChecks.every(checkName => {
      const check = relevantChecks.find(c => c.name === checkName);
      if (!check) {
        console.log(`Check "${checkName}" not found yet`);
        return false;
      }
      const completed = check.status === 'completed';
      console.log(`Check "${checkName}": ${check.status}${completed ? ` (${check.conclusion})` : ''}`);
      return completed;
    });

    if (allCompleted) {
      console.log('All required checks completed!');
      break;
    }

    await new Promise(resolve => setTimeout(resolve, 10000)); // 10초 대기
  }
};
