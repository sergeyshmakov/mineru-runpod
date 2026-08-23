import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Analytics } from "@/components/analytics";
import { Provider } from "@/components/provider";
import { ogImage, rssAlternates } from "@/lib/metadata";
import { siteDescription, siteName, siteUrl } from "@/lib/site";
import "./global.css";

export const metadata: Metadata = {
	metadataBase: new URL(siteUrl),
	title: {
		default: siteName,
		template: `%s | ${siteName}`,
	},
	description: siteDescription,
	icons: {
		icon: [{ url: "/favicon.png", type: "image/png" }],
	},
	alternates: {
		canonical: "/",
		types: rssAlternates,
	},
	openGraph: {
		type: "website",
		siteName,
		title: siteName,
		description: siteDescription,
		url: "/",
		images: [ogImage],
	},
	twitter: {
		card: "summary_large_image",
		title: siteName,
		description: siteDescription,
		images: [ogImage],
	},
};

export default function RootLayout({ children }: { children: ReactNode }) {
	return (
		<html lang="en" suppressHydrationWarning>
			<body className="flex min-h-screen flex-col antialiased">
				<Provider>{children}</Provider>
				<Analytics />
			</body>
		</html>
	);
}
