// Cloudflare Web Analytics. The site is served by GitHub Pages, not proxied
// through Cloudflare, so the beacon has to be injected manually on every page.
//
// The rendered attribute reads data-cf-beacon="{&quot;token&quot;: …}". That is
// correct, not broken: the HTML parser decodes the entities, so getAttribute
// returns raw JSON and the beacon posts to /cdn-cgi/rum as expected.

const CF_BEACON_TOKEN = "83b8c1b967de4691b508fa301d309bd3";

export function Analytics() {
	return (
		<script
			type="module"
			src="https://static.cloudflareinsights.com/beacon.min.js"
			data-cf-beacon={JSON.stringify({ token: CF_BEACON_TOKEN })}
		/>
	);
}
