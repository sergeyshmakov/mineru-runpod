import { remarkMdxMermaid } from "fumadocs-core/mdx-plugins";
import { defineConfig } from "fumadocs-mdx/config";

export default defineConfig({
	mdxOptions: {
		remarkPlugins: (plugins) => [remarkMdxMermaid, ...plugins],
		// The overview links out to an upstream benchmark image. Fetching remote
		// images at build time to measure them makes the build depend on a third
		// party being reachable, so external images stay plain <img> elements.
		remarkImageOptions: {
			external: false,
		},
	},
});
