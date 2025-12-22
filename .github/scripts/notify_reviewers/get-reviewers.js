/**
 * Get reviewers from pull request and set outputs
 *
 * Environment variables:
 * - PR_NUMBER: The pull request number
 *
 * @param {object} github - GitHub API client
 * @param {object} context - GitHub Actions context
 * @param {object} core - GitHub Actions core utilities
 */
module.exports = async ({ github, context, core }) => {
  const prNumber = parseInt(process.env.PR_NUMBER, 10);

  const { data: pr } = await github.rest.pulls.get({
    owner: context.repo.owner,
    repo: context.repo.repo,
    pull_number: prNumber,
  });

  const reviewers = pr.requested_reviewers || [];
  const teamReviewers = pr.requested_teams || [];

  const reviewerNames = reviewers.map(r => r.login);
  const teamNames = teamReviewers.map(t => t.name);

  const allReviewers = [...reviewerNames, ...teamNames.map(t => `team:${t}`)];

  console.log('Reviewers:', allReviewers.join(', '));
  core.setOutput('reviewers', allReviewers.join(', '));
  core.setOutput('has_reviewers', allReviewers.length > 0 ? 'true' : 'false');
};
