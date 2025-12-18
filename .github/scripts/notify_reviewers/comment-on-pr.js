/**
 * Comment on pull request with reviewer notification
 *
 * Environment variables:
 * - REVIEWERS: Comma-separated list of reviewers
 *
 * @param {object} github - GitHub API client
 * @param {object} context - GitHub Actions context
 * @param {object} core - GitHub Actions core utilities
 */
module.exports = async ({ github, context, core }) => {
  const reviewers = process.env.REVIEWERS;

  await github.rest.issues.createComment({
    owner: context.repo.owner,
    repo: context.repo.repo,
    issue_number: context.payload.pull_request.number,
    body: `🔔 Review notification sent to: ${reviewers}`
  });
};
