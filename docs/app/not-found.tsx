import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
	title: "Page not found",
	robots: {
		index: false,
		follow: false,
	},
};

export default function NotFound() {
	return (
		<main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-6 py-24">
			<p className="text-sm font-medium text-fd-muted-foreground">404</p>
			<h1 className="mt-3 text-4xl font-semibold tracking-tight">
				Page not found
			</h1>
			<p className="mt-4 text-fd-muted-foreground">
				The requested page does not exist in the current documentation.
			</p>
			<Link
				href="/getting-started/overview/"
				className="mt-7 w-fit font-medium underline underline-offset-4"
			>
				Open the documentation
			</Link>
		</main>
	);
}
