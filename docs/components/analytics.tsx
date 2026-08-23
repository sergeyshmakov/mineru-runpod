// Cloudflare Web Analytics. The site is served by GitHub Pages, not proxied
// through Cloudflare, so the beacon has to be injected manually on every page.
//
// The rendered attribute reads data-cf-beacon="{&quot;token&quot;: …}". That is
// correct, not broken: the HTML parser decodes the entities, so getAttribute
// returns raw JSON and the beacon posts to /cdn-cgi/rum as expected.
//
// `async` is load-bearing: React only treats a script element as a hoistable
// resource when it is async, and warns about any other script rendered inside a
// component because client renders would not execute it.

const CF_BEACON_TOKEN = "83b8c1b967de4691b508fa301d309bd3";

export function Analytics() {
	return (
		<script
			async
			src="https://static.cloudflareinsights.com/beacon.min.js"
			data-cf-beacon={JSON.stringify({ token: CF_BEACON_TOKEN })}
		/>
	);
}
