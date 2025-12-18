/**
 * Get reviewers from pull request and set outputs
 *
 * @param {object} github - GitHub API client
 * @param {object} context - GitHub Actions context
 * @param {object} core - GitHub Actions core utilities
 */
module.exports = async ({ github, context, core }) => {
  const reviewers = context.payload.pull_request.requested_reviewers || [];
  const teamReviewers = context.payload.pull_request.requested_teams || [];

  const reviewerNames = reviewers.map(r => r.login);
  const teamNames = teamReviewers.map(t => t.name);

  const allReviewers = [...reviewerNames, ...teamNames.map(t => `team:${t}`)];

  console.log('Reviewers:', allReviewers.join(', '));
  core.setOutput('reviewers', allReviewers.join(', '));
  core.setOutput('has_reviewers', allReviewers.length > 0 ? 'true' : 'false');
};
