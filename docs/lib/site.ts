export const siteName = "mineru-runpod";
export const siteDescription =
	"Deploy MinerU 3.4 on RunPod Serverless. The open-source endpoint scales to zero and returns Markdown, structured JSON, and extracted images.";
export const siteUrl = "https://mineru.shmakov.tools";
export const repositoryUrl = "https://github.com/sergeyshmakov/mineru-runpod";

// Referral credit only fires for new accounts arriving through the RunPod
// homepage link, so every "learn more" CTA uses that. The Hub listing is the
// deploy-now surface for people who already have an account, and carries no
// ref parameter because it is inert on console deep links.
export const runpodReferralUrl = "https://runpod.io?ref=31jdfpnq";
export const runpodHubUrl =
	"https://console.runpod.io/hub/sergeyshmakov/mineru-runpod";

export const modelCardUrl =
	"https://huggingface.co/opendatalab/MinerU2.5-Pro-2605-1.2B";

export const ogImagePath = "/og-default.png";
export const ogImageAlt = "MinerU document parsing deployed on RunPod Serverless";

export const authorName = "Sergei Shmakov";
export const authorUrl = "https://github.com/sergeyshmakov";

export function absoluteUrl(path: string): URL {
	const url = new URL(path, siteUrl);
	if (!url.pathname.endsWith("/") && !url.pathname.includes(".")) {
		url.pathname += "/";
	}
	return url;
}
