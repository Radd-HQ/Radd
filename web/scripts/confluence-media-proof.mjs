/**
 * Does an imported Confluence video actually PLAY? (spec 117, RADD-1022)
 *
 * The conversion was already proven: the fence carries the right kind and a
 * resolved attachment URL. That is not the same as a working player — a `<video>`
 * with a URL the server will not range-serve shows a black box with controls, and
 * looks identical in every assertion short of asking the element itself.
 *
 * So this asks the element: does it report readable metadata, a real duration,
 * and a non-zero intrinsic size? Those only exist once the browser has fetched
 * and decoded the header, which means the endpoint, the bytes and the codec all
 * worked.
 *
 * Usage:
 *   node scripts/confluence-media-proof.mjs <baseUrl> <spaceSlug> <pageSlug> <email> <password>
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, pageSlug, email, password] = process.argv.slice(2);
const PORT = 9453;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-media-proof-profile");

/** Wait for the browser to load enough of the file to describe it. */
const MEDIA_PROBE = `(async () => {
  const video = document.querySelector("video");
  if (!video) return { found: false };
  if (video.readyState < 1) {
    await new Promise((done) => {
      const timer = setTimeout(done, 15000);
      video.addEventListener("loadedmetadata", () => { clearTimeout(timer); done(); }, { once: true });
      video.addEventListener("error", () => { clearTimeout(timer); done(); }, { once: true });
    });
  }
  return {
    found: true,
    src: video.currentSrc || video.getAttribute("src") || "",
    readyState: video.readyState,
    duration: video.duration,
    width: video.videoWidth,
    height: video.videoHeight,
    hasControls: video.controls,
    errorCode: video.error ? video.error.code : 0,
  };
})()`;

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE });
  const checks = {};

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);
  checks["headless chrome reports a real pointer"] = await session.hoverCapable();

  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${pageSlug}`, 3000);
  await sleep(1500);
  const media = await session.eval(MEDIA_PROBE);

  checks["the page renders a <video> element"] = media.found === true;
  checks["…pointing at an imported attachment"] =
    typeof media.src === "string" && media.src.includes("/api/v1/attachments/");
  checks["…with controls"] = media.hasControls === true;
  checks["…and no media error"] = media.errorCode === 0;
  // The ones that only pass if the bytes really arrived and decoded.
  checks["the browser read its METADATA (readyState >= 1)"] = media.readyState >= 1;
  checks["…a real duration"] = Number.isFinite(media.duration) && media.duration > 0;
  checks["…and real dimensions"] = media.width > 0 && media.height > 0;

  const shot = await session.send("Page.captureScreenshot", { format: "png" });
  report(checks, media);
  return shot.data;
}

main()
  .then(async (png) => {
    const { writeFile } = await import("node:fs/promises");
    const dir = process.env.PROOF_OUT || "/tmp";
    await writeFile(`${dir}/confluence-media.png`, Buffer.from(png, "base64"));
    console.log(`screenshot: ${dir}/confluence-media.png`);
    process.exit(0);
  })
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
