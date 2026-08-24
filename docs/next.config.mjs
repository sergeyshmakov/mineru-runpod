import { createMDX } from "fumadocs-mdx/next";

const withMDX = createMDX();

/** @type {import("next").NextConfig} */
const config = {
	images: {
		unoptimized: true,
	},
	output: "export",
	reactStrictMode: true,
	trailingSlash: true,
	turbopack: {
		root: process.cwd(),
	},
};

export default withMDX(config);
