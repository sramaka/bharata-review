/**
 * Bhārata Saṅgraha review portal — save backend (Google Apps Script web app).
 *
 * The portal POSTs {page, content, log, saved_at} as text/plain JSON. Each save is
 *   1. committed to GitHub as output/verified/page_XXX.md, which triggers the
 *      "Rebuild review site" GitHub Action so the live site shows the saved page, and
 *   2. written to the Drive folder bharata_verified_pages/ as a backup.
 *
 * The GitHub token lives only in Script Properties (Project Settings → Script Properties):
 *   GITHUB_TOKEN   fine-grained token for sramaka/bharata-review with Contents: Read and write
 * Without it, saves go to Drive only.
 *
 * Deploy: Deploy → Manage deployments → edit the existing web app → Version: New version,
 * so the URL in the portal stays the same. Execute as: Me; Who has access: Anyone.
 */

const GITHUB_OWNER = 'sramaka';
const GITHUB_REPO = 'bharata-review';
const GITHUB_BRANCH = 'main';
const VERIFIED_PATH = 'output/verified';
const DRIVE_FOLDER = 'bharata_verified_pages';
const MAX_CONTENT_CHARS = 500000;

function doPost(e) {
  // One save at a time, so two quick saves of the same page cannot race on the file's sha
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const body = JSON.parse(e.postData.contents);
    const page = String(body.page || '');
    const content = String(body.content || '');
    if (!/^\d{3}$/.test(page)) return reply({ ok: false, error: 'Invalid page number: ' + page });
    if (!content.includes('## १. मूलपाठः') || content.length > MAX_CONTENT_CHARS) {
      return reply({ ok: false, error: 'Content is not a review page' });
    }

    const result = { page: page, drive: saveToDrive(page, content) };
    const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
    result.github = token ? saveToGitHub(token, page, content, body.saved_at) : { ok: false, skipped: true };
    // GitHub is the record when it is set up; Drive alone counts only when it is not
    result.ok = token ? result.github.ok : result.drive.ok;
    return reply(result);
  } catch (err) {
    return reply({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

/** Health check: open the web app URL in a browser to see whether GitHub saving is set up. */
function doGet() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  return reply({ ok: true, github: Boolean(token), repo: GITHUB_OWNER + '/' + GITHUB_REPO });
}

function saveToDrive(page, content) {
  try {
    const folders = DriveApp.getFoldersByName(DRIVE_FOLDER);
    const folder = folders.hasNext() ? folders.next() : DriveApp.createFolder(DRIVE_FOLDER);
    const name = 'page_' + page + '.md';
    const files = folder.getFilesByName(name);
    if (files.hasNext()) files.next().setContent(content);
    else folder.createFile(name, content, MimeType.PLAIN_TEXT);
    return { ok: true };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

function saveToGitHub(token, page, content, savedAt) {
  const path = VERIFIED_PATH + '/page_' + page + '.md';
  const url = 'https://api.github.com/repos/' + GITHUB_OWNER + '/' + GITHUB_REPO + '/contents/' + path;
  const headers = {
    Authorization: 'Bearer ' + token,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  };

  // Retry once if the file changed between reading its sha and writing (HTTP 409)
  for (let attempt = 0; attempt < 2; attempt++) {
    const current = UrlFetchApp.fetch(url + '?ref=' + GITHUB_BRANCH, { headers: headers, muteHttpExceptions: true });
    let sha = null;
    if (current.getResponseCode() === 200) {
      const existing = JSON.parse(current.getContentText());
      sha = existing.sha;
      const existingText = Utilities.newBlob(Utilities.base64Decode(existing.content.replace(/\n/g, ''))).getDataAsString('UTF-8');
      if (existingText === content) return { ok: true, unchanged: true };
    } else if (current.getResponseCode() !== 404) {
      return { ok: false, error: 'GitHub read failed (' + current.getResponseCode() + '): ' + current.getContentText().slice(0, 300) };
    }

    const payload = {
      message: 'Verify page ' + page + ' (review portal' + (savedAt ? ', ' + savedAt : '') + ')',
      content: Utilities.base64Encode(content, Utilities.Charset.UTF_8),
      branch: GITHUB_BRANCH,
    };
    if (sha) payload.sha = sha;
    const res = UrlFetchApp.fetch(url, {
      method: 'put',
      contentType: 'application/json',
      headers: headers,
      payload: JSON.stringify(payload),
      muteHttpExceptions: true,
    });
    const code = res.getResponseCode();
    if (code === 200 || code === 201) {
      return { ok: true, commit: JSON.parse(res.getContentText()).commit.sha };
    }
    if (code !== 409 || attempt === 1) {
      return { ok: false, error: 'GitHub write failed (' + code + '): ' + res.getContentText().slice(0, 300) };
    }
  }
}

/**
 * Run this once from the editor (select testGitHub → ▶ Run) to grant the "connect to an
 * external service" permission and check the token: the log shows the repo GitHub sees.
 */
function testGitHub() {
  const token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('GITHUB_TOKEN is not set in Project Settings → Script Properties');
  const res = UrlFetchApp.fetch('https://api.github.com/repos/' + GITHUB_OWNER + '/' + GITHUB_REPO, {
    headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
    muteHttpExceptions: true,
  });
  const body = JSON.parse(res.getContentText());
  Logger.log('GitHub replied ' + res.getResponseCode() + ': ' +
             (body.full_name ? body.full_name + ', can push: ' + (body.permissions && body.permissions.push) : body.message));
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
