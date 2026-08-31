## [1.11.0](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.10.1...v1.11.0) (2026-08-31)

### ⚠ Job Contract Changes (action may be required)

* **schema:** enforcement requires an allow-listed server_url host ([e398a18](https://github.com/sergeyshmakov/mineru-runpod/commit/e398a18654c6e8200a3d42fd26da776a6f4419ed))

### ⚠ Compatibility Changes (action may be required)

* **client:** use the shared runpod-doc-client instead of private copies ([e05f1ab](https://github.com/sergeyshmakov/mineru-runpod/commit/e05f1ab6dd3442edb30be02dd913b25e82847062))

### Features

* **harness:** adopt v0.7.1 and refuse a response the gateway would discard ([47cd6b6](https://github.com/sergeyshmakov/mineru-runpod/commit/47cd6b66733f3d5a19237851dbab1a58af385306))

### Bug Fixes

* **client:** let an operator opt back in to fetching from a private address ([17c37c5](https://github.com/sergeyshmakov/mineru-runpod/commit/17c37c508aeada1a9e5e91749a7efe65deeb412d))
* **client:** name the response-size cap when the gateway drops the output ([fc0b6f0](https://github.com/sergeyshmakov/mineru-runpod/commit/fc0b6f0e4860221619dbb4c80bacb509768a02ef))
* **deploy:** delete endpoints for real, and apply the execution timeout ([ac092d6](https://github.com/sergeyshmakov/mineru-runpod/commit/ac092d65207d0b8b5a0dc00dae3eba2484e2301b))
* **deps:** stop excluding lockfile-only vulnerabilities from security updates ([d24cd20](https://github.com/sergeyshmakov/mineru-runpod/commit/d24cd20ce979587c51eda03d88be09909dc8e81b))
* **destroy:** tell an absent endpoint from one that may still be running ([e83abd4](https://github.com/sergeyshmakov/mineru-runpod/commit/e83abd486ab20a45aeb0306e097683dc7548715a))
* **handler:** re-export _package_inline, and assert the whole compat surface ([b20c6d7](https://github.com/sergeyshmakov/mineru-runpod/commit/b20c6d798b9fadc17021e7ee7b3940ca8f2fe3b7))
* **lifecycle:** forward writes to the compat counter names, not just reads ([84d7f0e](https://github.com/sergeyshmakov/mineru-runpod/commit/84d7f0e4e65ac5fe2e3000de8c08f5f8fca184c0))
* **schema:** a caller cannot borrow the operator's local-fetch exemption ([9f673d6](https://github.com/sergeyshmakov/mineru-runpod/commit/9f673d6e5bc30662b0df4f070965cd9255092659))
* **schema:** apply the outbound-target policy to server_url ([7dd6c06](https://github.com/sergeyshmakov/mineru-runpod/commit/7dd6c0687847fbd7fa0a4865bb793eb7af2159f0))
* **schema:** make the server_url target policy opt-in ([fafe40d](https://github.com/sergeyshmakov/mineru-runpod/commit/fafe40d8e2325faac6db81dd159bfe644ccb9f4d))
* **schema:** scope the private-server exemption to named hosts ([949976b](https://github.com/sergeyshmakov/mineru-runpod/commit/949976b7eec70a5b7a4663069b28b943f2c595ca))
* **telemetry:** both since-boot gauges reported zero for the life of the process ([9eab0b1](https://github.com/sergeyshmakov/mineru-runpod/commit/9eab0b1d951336b6de736f0f59726173dea6fe68))
* **telemetry:** every log a job produced was dropped by the exporter ([a124b5e](https://github.com/sergeyshmakov/mineru-runpod/commit/a124b5ee4dff3a5ae5ec7d71bed4bee244184c84))
* **test:** declare PyYAML, and correct the timeout guidance the last commit invalidated ([4acdd04](https://github.com/sergeyshmakov/mineru-runpod/commit/4acdd040b35f737e5582ad33d0973bfdf7fadd23))

### Refactoring

* bring every file under a 500-line cap, and enforce it ([b7c8b48](https://github.com/sergeyshmakov/mineru-runpod/commit/b7c8b485b2258ec2c41715e8251aa12ab219e4a4))

### Documentation

* **agents:** never mark a change breaking without asking ([bb3b8d8](https://github.com/sergeyshmakov/mineru-runpod/commit/bb3b8d8f949a78ea05bc49ed8ea255219379f0ef))
* **deploy:** say that deploy.py applies the execution timeout ([7e67499](https://github.com/sergeyshmakov/mineru-runpod/commit/7e67499b5eb06d5b3d84b7c1312ec8c77977c4cd))
* **hub:** describe server_url enforcement as the allow-list it now is ([19a52a1](https://github.com/sergeyshmakov/mineru-runpod/commit/19a52a153d7ae1cc1ca1d26a973bcc883e8f7c4e))
* **hub:** name the pinned MinerU series in the Hub listing ([5f51e56](https://github.com/sergeyshmakov/mineru-runpod/commit/5f51e566bb01764723d22492db4772c162078081))
* **readme:** write down the versioning policy, and make it enforceable ([8192d49](https://github.com/sergeyshmakov/mineru-runpod/commit/8192d492eb1295b8e06ad112ef35c1dd38d02b60))
* **reference:** give versioning its own page instead of a buried section ([e56c311](https://github.com/sergeyshmakov/mineru-runpod/commit/e56c3116fb4c891d45672931999c8e79e19134c6))

## [1.10.1](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.10.0...v1.10.1) (2026-08-24)

### Bug Fixes

* two defects found while reviewing the sibling worker ([9074408](https://github.com/sergeyshmakov/mineru-runpod/commit/90744083cc043e12bdf6132a8815534261184950))

### Documentation

* correct the baked-weight figure, which was off by 4x ([a60e9b7](https://github.com/sergeyshmakov/mineru-runpod/commit/a60e9b7f2460a35b21bfb2f44c0af4850066b84c))
* repoint the backlog links at the moved guides ([53cc483](https://github.com/sergeyshmakov/mineru-runpod/commit/53cc4833b6fab55319c27baf613ac8d30979e90c))
* **site:** give each page its own Twitter card ([6673dde](https://github.com/sergeyshmakov/mineru-runpod/commit/6673dde854353ad1dd6f638f6d72ba45ef7b95b7))
* **site:** give the site its own mark and a deploy button on every page ([34a16a6](https://github.com/sergeyshmakov/mineru-runpod/commit/34a16a62d6f7616114daf33ea421cf6638d59a9f))
* **site:** rebuild the documentation site on Fumadocs ([75dec24](https://github.com/sergeyshmakov/mineru-runpod/commit/75dec24db0f20b3e05cc1d93d772047224ec9926))
* **site:** redraw the social card from the new mark ([6ab6159](https://github.com/sergeyshmakov/mineru-runpod/commit/6ab6159ce058e330e2e066bec0295e265fe3b653))
* **site:** render external MDX images without next/image ([83e866c](https://github.com/sergeyshmakov/mineru-runpod/commit/83e866cdb11a4c292af92e65883e080562cef5cf))
* **site:** replace the hero with a mark-derived graphic ([e57ed18](https://github.com/sergeyshmakov/mineru-runpod/commit/e57ed18c520e2252296af614074f7e8106c1ecdf))
* warn that this is not an official MinerU project ([ec5d770](https://github.com/sergeyshmakov/mineru-runpod/commit/ec5d7702a7ad7edf8cb0297848cf49c07293279b))

## [1.10.0](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.9.0...v1.10.0) (2026-08-21)

### Features

* count what a successful response could not carry ([25b86fa](https://github.com/sergeyshmakov/mineru-runpod/commit/25b86fa9ca4c100f0a2a9581afff3b9271737fe1))

### Bug Fixes

* require the artifact a response exists for ([8542c36](https://github.com/sergeyshmakov/mineru-runpod/commit/8542c3664deef012b4bfb4d061a72e8567a7e3d5))

### Refactoring

* own the probe gate instead of tracking the harness ([c6eaa55](https://github.com/sergeyshmakov/mineru-runpod/commit/c6eaa55c154710ed8703363ef1dd32af3203e84f))
* source GPU and cache diagnostics from the harness ([dd14de1](https://github.com/sergeyshmakov/mineru-runpod/commit/dd14de146a54863c68224a8341a1930391a75f0c))
* source input transport and target checks from the harness ([9f9aac0](https://github.com/sergeyshmakov/mineru-runpod/commit/9f9aac0ec399de146e9ca9102cda14fd3b85a54a))
* source result packaging from the harness ([9a89dc4](https://github.com/sergeyshmakov/mineru-runpod/commit/9a89dc448b99a9859f8461b8343fd91b93bbc94b))
* source structured logging and redaction from the harness ([aab37b7](https://github.com/sergeyshmakov/mineru-runpod/commit/aab37b7221d64c720ee5d1ebca139cbf322b9f2e))

### Documentation

* correct the image layout comment ([b22f5a5](https://github.com/sergeyshmakov/mineru-runpod/commit/b22f5a54a01ce287d09e638c00346c28b175b397))
* describe an incomplete response ([85b26fe](https://github.com/sergeyshmakov/mineru-runpod/commit/85b26febbcff71c373ba256ebb95b0c1a1a478fc))
* describe the worker harness ([21d3a19](https://github.com/sergeyshmakov/mineru-runpod/commit/21d3a1972b09826e17d1fcd12e209a36b29bb691))
* make the degraded example parse and name its overflow labels ([011f7e7](https://github.com/sergeyshmakov/mineru-runpod/commit/011f7e759bda1289f2e5048abba9d32109b1db3e))

### Build / Deps

* **deps-dev:** bump semantic-release from 25.0.8 to 25.0.9 in the npm-development group ([#22](https://github.com/sergeyshmakov/mineru-runpod/issues/22)) ([c331a41](https://github.com/sergeyshmakov/mineru-runpod/commit/c331a419bc50016a5d4db468e6e22f0a7d440452))
* **deps:** bump the docs-deps group in /docs with 2 updates ([#23](https://github.com/sergeyshmakov/mineru-runpod/issues/23)) ([0256269](https://github.com/sergeyshmakov/mineru-runpod/commit/0256269977b62b36532d8f1c15b0a2f8c363f1dd))
* **deps:** consolidate Dependabot updates ([bf231d7](https://github.com/sergeyshmakov/mineru-runpod/commit/bf231d759122e8f2313a9ca6a2ba03dd00e25ef5))
* **deps:** correct Dependabot group limit ([baf721f](https://github.com/sergeyshmakov/mineru-runpod/commit/baf721f3704f47fc44ed42ab40d5405f3faf33d3))
* **deps:** move the worker harness pin to v0.2.0 ([22cab34](https://github.com/sergeyshmakov/mineru-runpod/commit/22cab346de7ebf191c83ee8cfcfe854dc374b499))
* **deps:** move the worker harness pin to v0.3.0 ([9bcb9d5](https://github.com/sergeyshmakov/mineru-runpod/commit/9bcb9d50da3511a43e3a7908b4d5610cb5f694c8))
* **deps:** move the worker harness pin to v0.4.0 ([ccf6627](https://github.com/sergeyshmakov/mineru-runpod/commit/ccf66271a5d82b034335782d79e688e289b9bc31))
* **deps:** pin the worker harness package ([842a206](https://github.com/sergeyshmakov/mineru-runpod/commit/842a20662c19dbac72c5d8eafc966e90f4d7d4e3))
* **deps:** restore release notes by pinning the changelog preset ([#20](https://github.com/sergeyshmakov/mineru-runpod/issues/20)) ([5160306](https://github.com/sergeyshmakov/mineru-runpod/commit/51603060b01dba6370e34440d672a478c6e676e2))
* let hatchling accept the pinned harness reference ([27b0fd5](https://github.com/sergeyshmakov/mineru-runpod/commit/27b0fd5f4214e03f42824f70d544e6dca2941c42)), closes [#5](https://github.com/sergeyshmakov/mineru-runpod/issues/5)

## [1.9.0](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.8.4...v1.9.0) (2026-08-13)

### Features

* **worker:** normalize the job input surface and add endpoint-level limits ([#19](https://github.com/sergeyshmakov/mineru-runpod/issues/19)) ([4bd9219](https://github.com/sergeyshmakov/mineru-runpod/commit/4bd92198f561249ad82059ae94636a032ba8bc62))

### Documentation

* add Cloudflare Web Analytics beacon to the docs site ([#18](https://github.com/sergeyshmakov/mineru-runpod/issues/18)) ([357cc36](https://github.com/sergeyshmakov/mineru-runpod/commit/357cc362a4e8101bf18b11a0557f03221cf267d1))
* align SEO, API guidance, and OpenTelemetry documentation ([#17](https://github.com/sergeyshmakov/mineru-runpod/issues/17)) ([314385d](https://github.com/sergeyshmakov/mineru-runpod/commit/314385d192535abf06756bfcaff406f454ef0e1e))
* explain that the Hub template builds an image rather than pulling one ([6032696](https://github.com/sergeyshmakov/mineru-runpod/commit/6032696b34ee56afcb359929d28beea3501d879b))
* migrate site to mineru.shmakov.tools ([#16](https://github.com/sergeyshmakov/mineru-runpod/issues/16)) ([b22b1cf](https://github.com/sergeyshmakov/mineru-runpod/commit/b22b1cf733591a485776716c31fc4596e2f82252))
* stop wide tables overlapping the sidebar and give the nav a backdrop ([5dabfad](https://github.com/sergeyshmakov/mineru-runpod/commit/5dabfad85c9f8f7b5234aaf1acd57fcfa4a793fe))
* thin the header veil so the backdrop blur is actually visible ([dfab1e3](https://github.com/sergeyshmakov/mineru-runpod/commit/dfab1e35bd38997e06d417f7b023ee9acd0836d1))

### Build / Deps

* **deps-dev:** bump the npm-development group with 6 updates ([#15](https://github.com/sergeyshmakov/mineru-runpod/issues/15)) ([e01fd0b](https://github.com/sergeyshmakov/mineru-runpod/commit/e01fd0be4663b6e436f485462e52db53a3fa3451))
* **deps:** bump the docs-deps group in /docs with 4 updates ([#14](https://github.com/sergeyshmakov/mineru-runpod/issues/14)) ([63880a9](https://github.com/sergeyshmakov/mineru-runpod/commit/63880a933a4616c45140f10987a70911de797092))

## [1.8.4](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.8.3...v1.8.4) (2026-08-01)

### Bug Fixes

* **worker:** drain in-flight jobs on SIGTERM instead of failing them ([#12](https://github.com/sergeyshmakov/mineru-runpod/issues/12)) ([23d8d02](https://github.com/sergeyshmakov/mineru-runpod/commit/23d8d0218fab36257af9ab2c025ace004376e37e))

## [1.8.0](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.7.1...v1.8.0) (2026-07-12)

### Features

* **worker:** upgrade MinerU to 3.4 and add effort control ([#10](https://github.com/sergeyshmakov/mineru-runpod/issues/10)) ([af44cc6](https://github.com/sergeyshmakov/mineru-runpod/commit/af44cc6bfc3d05b066a2c1b518fb7f12fdfd5a5c))

### Build / Deps

* **deps-dev:** bump the npm-development group with 4 updates ([#6](https://github.com/sergeyshmakov/mineru-runpod/issues/6)) ([d1b800c](https://github.com/sergeyshmakov/mineru-runpod/commit/d1b800cc80209732e246f08feb67cb9ea3e5cd7a))
* **deps:** bump the docs-deps group in /docs with 4 updates ([#7](https://github.com/sergeyshmakov/mineru-runpod/issues/7)) ([79b581e](https://github.com/sergeyshmakov/mineru-runpod/commit/79b581e4ac98270e286e703e982dddf3bb9d097f))

## [1.7.1](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.7.0...v1.7.1) (2026-07-12)

### Bug Fixes

* drop packaging progress_update that races the final result post ([#9](https://github.com/sergeyshmakov/mineru-runpod/issues/9)) ([8dd3b38](https://github.com/sergeyshmakov/mineru-runpod/commit/8dd3b38ec8cf024d36c148f1714fc5aa276fc6e3)), closes [#4](https://github.com/sergeyshmakov/mineru-runpod/issues/4)

### Documentation

* add self-host MinerU API blog post ([0d82d9b](https://github.com/sergeyshmakov/mineru-runpod/commit/0d82d9b7c3d2b2106707dd1fb8d4eb34b4260daf))
* badge links fix ([f5327c4](https://github.com/sergeyshmakov/mineru-runpod/commit/f5327c4a957317b723b43b9b4401a021326dd2f0))
* correct cold-start and model-download claims in self-host post ([7cc8b0d](https://github.com/sergeyshmakov/mineru-runpod/commit/7cc8b0d01d5cbeadd0593083ac47555a0f25eb1b))
* drop batch from public docs; document worker-scaling for parallelism ([10ba60e](https://github.com/sergeyshmakov/mineru-runpod/commit/10ba60e6d1d7fead022ad625039af90d9e0a87b5))
* fix 404 blog cross-links to use dated slugs ([019c9f5](https://github.com/sergeyshmakov/mineru-runpod/commit/019c9f53dc96e62a31badfb06f98e7cf9da91b1f))
* update link titles in docs ([2bd7732](https://github.com/sergeyshmakov/mineru-runpod/commit/2bd7732de30a0358fc8a6ff4d0ddc7bade2e14e8))

### Build / Deps

* **deps-dev:** bump the npm-development group with 6 updates ([0f41541](https://github.com/sergeyshmakov/mineru-runpod/commit/0f415419e5b4f457eaff9a9237d53dde85effd01))
* **deps:** bump the docs-deps group in /docs with 3 updates ([065405a](https://github.com/sergeyshmakov/mineru-runpod/commit/065405a1a822c2a0965b8963dc377288da3611d6))
* **deps:** regenerate docs lockfile for astro 6.4.4; bump sharp to 0.34.5 ([1acdef3](https://github.com/sergeyshmakov/mineru-runpod/commit/1acdef3940bd1feac22126c7ced4f95c9cbc203b))

## [1.7.0](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.6.4...v1.7.0) (2026-06-08)

### Features

* **client:** add MinerU API-compatible client (MineruApiClient) ([62cd9b6](https://github.com/sergeyshmakov/mineru-runpod/commit/62cd9b6a769bf86ac261584622890137f353f463))
* **worker:** add archive_format (tar.gz/zip) for archive transports ([e90d079](https://github.com/sergeyshmakov/mineru-runpod/commit/e90d0790abfb73d1f291dc7a96a5b601ce2de68c))

### Bug Fixes

* **client:** reject MinerU callback param and add archive download timeouts ([68e7193](https://github.com/sergeyshmakov/mineru-runpod/commit/68e719314f2df166391f1e0b3e6b9dcee9cda70f))

### Documentation

* add concurrency guide and fix stale GPU sizing guidance ([da938a4](https://github.com/sergeyshmakov/mineru-runpod/commit/da938a4d306a404a625e9beea6fe4b89d3e60dd5))

## [1.6.4](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.6.3...v1.6.4) (2026-06-07)

### Bug Fixes

* update docs and readme stale version + revert tests to 4090 ([7939c39](https://github.com/sergeyshmakov/mineru-runpod/commit/7939c393d6fcfbaee4d1a0c4e539ab7f360c35cb))

### Documentation

* add blog post ([6950a7c](https://github.com/sergeyshmakov/mineru-runpod/commit/6950a7c4318e9a76cf3ae9f351180dc5e43bed5b))
* blog post about popular runpod error ([8a25752](https://github.com/sergeyshmakov/mineru-runpod/commit/8a2575299b160374ae9bb641f4ef7077db41eac7))
* blog post crosslink ([2eb0e0b](https://github.com/sergeyshmakov/mineru-runpod/commit/2eb0e0b3da1ff3fb10a74a7622248a3ff0e53b14))
* example + blog post ([6eb311a](https://github.com/sergeyshmakov/mineru-runpod/commit/6eb311a6ed7ec5c82d6e7f00bc58f809dca5af93))
* fix links in blog posts ([6fdc68e](https://github.com/sergeyshmakov/mineru-runpod/commit/6fdc68e97d3a650fa1cc279ff8ed17c34dd8fd2c))
* show debug block in failure response example ([21f5a11](https://github.com/sergeyshmakov/mineru-runpod/commit/21f5a11ef5990d90a7c77374d145e23e08e9cf12))
* update numbers in blog post ([e742c86](https://github.com/sergeyshmakov/mineru-runpod/commit/e742c86346a8073deb69fff600c27f14d23ab724))

## [1.6.3](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.6.2...v1.6.3) (2026-06-02)

### Bug Fixes

* **hub:** switch test GPU to A40 ([dbad547](https://github.com/sergeyshmakov/mineru-runpod/commit/dbad54764d9c15b6b93cb7f3825d4acda2532641))

## [1.6.2](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.6.1...v1.6.2) (2026-06-02)

### Bug Fixes

* **hub:** switch test GPU to A5000 ([2804636](https://github.com/sergeyshmakov/mineru-runpod/commit/280463691d95317b2a010d1cc38b59d39993a2f2))

## [1.6.1](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.6.0...v1.6.1) (2026-06-02)

### Bug Fixes

* bump runpod ci ([bc0d2cd](https://github.com/sergeyshmakov/mineru-runpod/commit/bc0d2cd48bec0bdca7591f1a1f29853015129f17))

### Documentation

* rename return to transport in network volumes guide ([a65c08c](https://github.com/sergeyshmakov/mineru-runpod/commit/a65c08cbf8010a76fc90937e57af06b57ec123f4))

## [1.6.0](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.5.1...v1.6.0) (2026-05-28)

### Features

* add transport + formats fields and unify response shape ([5fd5a8f](https://github.com/sergeyshmakov/mineru-runpod/commit/5fd5a8f9aac0498d508e57b537b54e087d3121b7))

## [1.5.1](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.5.0...v1.5.1) (2026-05-27)

### Bug Fixes

* add otel pacakges for tests ([4756f92](https://github.com/sergeyshmakov/mineru-runpod/commit/4756f922cb9b64f8dfcc0830bd65cdeb121fa7b4))

### Documentation

* **backlog:** re-verify Blackwell blocker against MinerU 3.2.0 ([2bc1365](https://github.com/sergeyshmakov/mineru-runpod/commit/2bc136510e8589d928e984bc29035e75b009b4e8))
* disclosure + ref update ([2637639](https://github.com/sergeyshmakov/mineru-runpod/commit/26376390698b5e43d13729c5cbf5e28a8d47c6ec))
* update docs and blog post about observability ([d0a2505](https://github.com/sergeyshmakov/mineru-runpod/commit/d0a250506ad3340836d0b37dbbae3c724186d15d))

## [1.5.0](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.4.0...v1.5.0) (2026-05-26)

### Features

* bump mineru to 3.2 ([6e70f45](https://github.com/sergeyshmakov/mineru-runpod/commit/6e70f4520f583bfb1bdeb40fe024a1205a8bfa21))

## [1.4.0](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.3.1...v1.4.0) (2026-05-26)

### Features

* add otel ([cf45542](https://github.com/sergeyshmakov/mineru-runpod/commit/cf45542737f791a572556a537e456afa76e3e9c7))

### Documentation

* add blog post about flash boot ([b214a38](https://github.com/sergeyshmakov/mineru-runpod/commit/b214a384a2c9f9a7aea09c124c2be592954ddc6d))
* align articles with latest info ([b8d2b60](https://github.com/sergeyshmakov/mineru-runpod/commit/b8d2b60151e616d1969ff1678acea6c60c445240))
* tune subheader text ([662aa74](https://github.com/sergeyshmakov/mineru-runpod/commit/662aa74ee5bebca71cf84ba3ebb72877ee203e9d))
* update docs about flash boot ([93fe53f](https://github.com/sergeyshmakov/mineru-runpod/commit/93fe53f96e6397ee60727a0cc738c924eea73028))

## [1.3.1](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.3.0...v1.3.1) (2026-05-26)

### Bug Fixes

* switch to 4090 + warmup test on JobScaler ([8599324](https://github.com/sergeyshmakov/mineru-runpod/commit/8599324a72fc40426841047637844dfcd6f935f2))

## [1.3.0](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.2.6...v1.3.0) (2026-05-26)

### Features

* add worker warmup ([348b1dc](https://github.com/sergeyshmakov/mineru-runpod/commit/348b1dc240e63bacbd8890e636f0a20216973270))

## [1.2.6](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.2.5...v1.2.6) (2026-05-26)

### Bug Fixes

* add logger debug ([b57c47f](https://github.com/sergeyshmakov/mineru-runpod/commit/b57c47f1578cb6a0f9cd00b40a30195891055f65))

## [1.2.5](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.2.4...v1.2.5) (2026-05-26)

### Bug Fixes

* revert to print logger because runpod doesn't support structured logs ([3539f86](https://github.com/sergeyshmakov/mineru-runpod/commit/3539f86394854d9519704a183a817c7553d8d93f))

### Documentation

* add blackwell workaround and backlog info ([16244e9](https://github.com/sergeyshmakov/mineru-runpod/commit/16244e92b67a2fe27febee52f261b5ddec4c9526))

## [1.2.4](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.2.3...v1.2.4) (2026-05-26)

### Bug Fixes

* import after refactor ([6803381](https://github.com/sergeyshmakov/mineru-runpod/commit/680338185c4e5a77cbf5dc3577f9a99d3b98c2f2))

## [1.2.3](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.2.2...v1.2.3) (2026-05-25)

### Bug Fixes

* bump cuda ([2e4411e](https://github.com/sergeyshmakov/mineru-runpod/commit/2e4411e1562d804ad7798fe163d3db672f7263db))

## [1.2.2](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.2.1...v1.2.2) (2026-05-25)

### Bug Fixes

* speedup models download with hf xet ([a940a6c](https://github.com/sergeyshmakov/mineru-runpod/commit/a940a6ce9e726e0f86230616ea36df91377716b4))

## [1.2.1](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.2.0...v1.2.1) (2026-05-25)

### Bug Fixes

* add higher cuda versions ([4514d55](https://github.com/sergeyshmakov/mineru-runpod/commit/4514d554f1cd02831b3dc3f74fed03d517f9f153))

## [1.2.0](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.27...v1.2.0) (2026-05-25)

### Features

* add structural logs support ([d864d8a](https://github.com/sergeyshmakov/mineru-runpod/commit/d864d8a2f0cac7f53aaaf7eaa8b02d753d9b3119))

## [1.1.27](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.26...v1.1.27) (2026-05-25)

### Bug Fixes

* refine hub descriptions ([ca93e91](https://github.com/sergeyshmakov/mineru-runpod/commit/ca93e91753c3807bf9bc535281ba5f86ec76af38))

## [1.1.26](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.25...v1.1.26) (2026-05-25)

### Bug Fixes

* shorten hub.json descriptions to stay under varchar 191 ([5a5fe47](https://github.com/sergeyshmakov/mineru-runpod/commit/5a5fe47aea8afab961c6a711a9dcbeee14be50a2))

## [1.1.25](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.24...v1.1.25) (2026-05-25)

### Bug Fixes

* trying to fix runpod hub workflow ([62ca5ec](https://github.com/sergeyshmakov/mineru-runpod/commit/62ca5ec3c1a5f5dccd3705260d2464bc983ac9d5))

## [1.1.24](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.23...v1.1.24) (2026-05-24)

### Bug Fixes

* trying exactly recommended readme badge to fix runpod hub publishing workflow ([1bf1ce5](https://github.com/sergeyshmakov/mineru-runpod/commit/1bf1ce542f533a2684059b7f884dc097a242d93d))

## [1.1.23](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.22...v1.1.23) (2026-05-24)

### Bug Fixes

* remove runpod-disabled folder ([091fd56](https://github.com/sergeyshmakov/mineru-runpod/commit/091fd56ca4516750cdc23e5694b3bc9e466acc4e))

## [1.1.22](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.21...v1.1.22) (2026-05-24)

### Bug Fixes

* add icon to hub.json ([40d5ff8](https://github.com/sergeyshmakov/mineru-runpod/commit/40d5ff8faab9ecf3c37c8642a2a2dbffe045f912))

## [1.1.21](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.20...v1.1.21) (2026-05-24)

### Bug Fixes

* make file symlink ([a390ad5](https://github.com/sergeyshmakov/mineru-runpod/commit/a390ad512aadd552fdea0b7f6d7adb9d05ef5a19))

## [1.1.20](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.19...v1.1.20) (2026-05-24)

### Bug Fixes

* add symlink to handler.py ([bf9be39](https://github.com/sergeyshmakov/mineru-runpod/commit/bf9be3913caad5a62f8decc93fca05bc01d373bb))

## [1.1.19](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.18...v1.1.19) (2026-05-24)

### Bug Fixes

* readme badge update ([a1236f2](https://github.com/sergeyshmakov/mineru-runpod/commit/a1236f254cc24c8b50abf91ecac616cf8c5440ec))

## [1.1.18](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.17...v1.1.18) (2026-05-24)

### Bug Fixes

* fixing runpod hub flow ([a8116fd](https://github.com/sergeyshmakov/mineru-runpod/commit/a8116fdb9585998cedc408fbe752c382bd6bde7a))

## [1.1.17](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.16...v1.1.17) (2026-05-24)

### Bug Fixes

* trying to add hub.json for hub ([1f38d12](https://github.com/sergeyshmakov/mineru-runpod/commit/1f38d129653fc1c55e55e8d67fe8b2a588ebc40c))

## [1.1.16](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.15...v1.1.16) (2026-05-24)

### Bug Fixes

* rename repo to fix hub workflow ([ec98e38](https://github.com/sergeyshmakov/mineru-runpod/commit/ec98e38744cfeec3102b0313567ebbd530bb3857))

## [1.1.15](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.14...v1.1.15) (2026-05-20)

### Bug Fixes

* revert back since don't help to hub release ([e15ba6f](https://github.com/sergeyshmakov/mineru-runpod/commit/e15ba6f32e1e0c9c4654debd6a65720d06b67fa0))

## [1.1.14](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.13...v1.1.14) (2026-05-20)

### Bug Fixes

* trying to fix runpod hub release ([f8c53c9](https://github.com/sergeyshmakov/mineru-runpod/commit/f8c53c9ee9b111268b9873046c2cfc4b9b22ba18))

### Documentation

* minor docs update ([1a3eaa6](https://github.com/sergeyshmakov/mineru-runpod/commit/1a3eaa6bdb28cff1c9c6d4a33f97aa592fab639b))
* shorten subheader ([7b1e4e6](https://github.com/sergeyshmakov/mineru-runpod/commit/7b1e4e6cc444587d772715fa1dfdf1f4899d4c7e))
* update docs + blog ([11587f5](https://github.com/sergeyshmakov/mineru-runpod/commit/11587f5d6b66ee52c4123c94fb0bd18540be7ace))

## [1.1.13](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.12...v1.1.13) (2026-05-20)

### Bug Fixes

* **docs:** audit troubleshooting + language claims against empirical evidence ([cc6f064](https://github.com/sergeyshmakov/mineru-runpod/commit/cc6f0645796953525cc84c343f375c030180b2a6))
* **docs:** correct per-page speed claims and Blackwell wording per empirical + upstream evidence ([e555a7a](https://github.com/sergeyshmakov/mineru-runpod/commit/e555a7a49844e144c5e03cea75b424494b4e6358))
* **hub:** bump container disk 30 -> 50 GB to accommodate baked-in models ([f8872aa](https://github.com/sergeyshmakov/mineru-runpod/commit/f8872aa4f35c68168c5dedd6dff8d14e76e77adc))

### Documentation

* add 'Supported GPU pools' reference table to choosing-gpu ([72b8407](https://github.com/sergeyshmakov/mineru-runpod/commit/72b84072f5af2de86199ebcb4fddbb90a37ea4ec))

## [1.1.12](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.11...v1.1.12) (2026-05-20)

### Bug Fixes

* **worker:** override HF_HUB_OFFLINE=0 inline on the model-bake RUN step ([70aa5fe](https://github.com/sergeyshmakov/mineru-runpod/commit/70aa5fe6a0fde95cb97bfcacc2256a8c5c8f9ddc))

## [1.1.11](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.10...v1.1.11) (2026-05-20)

### Bug Fixes

* **worker:** bake both MinerU models into image at build time ([fcbff51](https://github.com/sergeyshmakov/mineru-runpod/commit/fcbff513c76e54901d4f5ff7eee7a006ac1d6768))
* **worker:** symlink lowercase Cached Models dir to canonical HF case at startup ([da5ebb4](https://github.com/sergeyshmakov/mineru-runpod/commit/da5ebb488a04e956c4ac16f69b1cb6f2a709ee9b))

## [1.1.10](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.9...v1.1.10) (2026-05-20)

### Internal

* Manual version advance to recover from a semantic-release loop that kept generating duplicate `chore(release): 1.1.9` commits after the v2.0.0 rollback. The release pipeline tried to re-tag `v1.1.9` because the existing tag pointed at an orphaned commit; each push hit the same `fatal: tag 'v1.1.9' already exists` error after creating a new release commit. No user-facing changes vs 1.1.9; subsequent releases return to automated semantic-release bumping from this baseline.

### Build / Deps

* Added a `probe: true` input flag on the worker that returns a `/runpod-volume` filesystem dump for debugging RunPod Cached Models setup. The probe also simulates the tutorial's `resolve_snapshot_path` for both VLM and pipeline models and reports any stale `refs/main` or casing-mismatch failures. No effect on normal parse jobs.

## [1.1.9](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.8...v1.1.9) (2026-05-20)

### Bug Fixes

* **hub:** drop ADA_48_PRO from default GPU pools; refresh template metadata ([ac0f5df](https://github.com/sergeyshmakov/mineru-runpod/commit/ac0f5dfa5dfcbf7b8b3e4af8f54ca340ed8865ed))
* **hub:** expose configurable env vars via hub.json deploy-time form ([9ef4ae4](https://github.com/sergeyshmakov/mineru-runpod/commit/9ef4ae4c2d0dab5471f2ff657e68c17a02a8ac70))
* **worker:** add S3 output mode + BUCKET_* env support ([2f2451e](https://github.com/sergeyshmakov/mineru-runpod/commit/2f2451e60480cb1ae5cc8ec55e6325b0440063c3))
* **worker:** align API with MinerU 3.1.x — parse_document, file_* fields, 5 backends, multi-format input, debug observability ([b763659](https://github.com/sergeyshmakov/mineru-runpod/commit/b763659b580206749179afc4013d5d9d5fd4a6ee))
* **worker:** bump MinerU to 3.1.x and vLLM base to v0.11.2; switch to RunPod Cached Models ([07efb50](https://github.com/sergeyshmakov/mineru-runpod/commit/07efb504987484a697bd97b63bf1aa1dbd6434b3))

### Documentation

* align all documentation with MinerU 3.1.x official recommendations ([bac4137](https://github.com/sergeyshmakov/mineru-runpod/commit/bac413720d1b27eab939a04725942fd512511d0b))
* correct facts after independent source revalidation ([d2fed43](https://github.com/sergeyshmakov/mineru-runpod/commit/d2fed431764d9466ff088cf2df4592f35cf742d0))
* four new guides + README quickstart, schema table, cross-links ([9b8a237](https://github.com/sergeyshmakov/mineru-runpod/commit/9b8a237bce5bd2f0a9a0da46d66599664d2fdc79))
* minor updates to docs ([db17801](https://github.com/sergeyshmakov/mineru-runpod/commit/db17801a6783fd12f8bb5ea32d3ce5fa96b96890))

## [1.1.8](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.7...v1.1.8) (2026-05-19)

### Bug Fixes

* **client:** omit None end_page from payload; better error message fallback ([52dbc53](https://github.com/sergeyshmakov/mineru-runpod/commit/52dbc53ec3cf8499f16a157273f12f55477232c0))

## [1.1.7](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.6...v1.1.7) (2026-05-19)

### Bug Fixes

* **hub:** add test_input.json + switch pip to uv for faster builds ([561f7e7](https://github.com/sergeyshmakov/mineru-runpod/commit/561f7e7452c0419909c6faf638c318cef2a5f717))
* **hub:** set MINERU_VL_MODEL_NAME so the local vlm backend loads Pro-2604 ([1abd2ba](https://github.com/sergeyshmakov/mineru-runpod/commit/1abd2ba4eedef5f70f81fd755d806b83ce32e608))

## [1.1.6](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.5...v1.1.6) (2026-05-19)

### Bug Fixes

* **hub:** use python3 instead of python in Dockerfile ([3b0e778](https://github.com/sergeyshmakov/mineru-runpod/commit/3b0e778aa1479e8779edd75e1ba660e6542cf321))

## [1.1.5](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.4...v1.1.5) (2026-05-19)

### Bug Fixes

* **hub:** pre-cache MinerU weights in image; bump test timeout to 20 min ([3bbef3a](https://github.com/sergeyshmakov/mineru-runpod/commit/3bbef3ad62c2836d1128492fa295ab63014ad56b))

## [1.1.4](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.3...v1.1.4) (2026-05-19)

### Bug Fixes

* **hub:** switch test GPU from RTX 4090 to RTX A5000 ([be7a262](https://github.com/sergeyshmakov/mineru-runpod/commit/be7a26223507ada4cf783904abd0969b09e1a90d))
* **hub:** widen allowedCudaVersions to ease GPU supply constraints ([cc34711](https://github.com/sergeyshmakov/mineru-runpod/commit/cc347113f7b4d16a82bccdfe9f5c86e3452c6fad))

### Documentation

* update docs site styles ([75ced01](https://github.com/sergeyshmakov/mineru-runpod/commit/75ced01ee83212adcf4c854e4df23a7312facafe))

## [1.1.3](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.2...v1.1.3) (2026-05-19)

### Bug Fixes

* **hub:** correct GPU pool IDs (ADA_48 → ADA_48_PRO) ([844f1be](https://github.com/sergeyshmakov/mineru-runpod/commit/844f1befcf45bd0a24c10905d429d3aa531e5dc5))

### Documentation

* update docs stylings ([c512a90](https://github.com/sergeyshmakov/mineru-runpod/commit/c512a90ecb67d3d2de05b1845f5cfa1269821140))

## [1.1.2](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.1.1...v1.1.2) (2026-05-19)

### Bug Fixes

* **hub:** align manifests with official template schema ([bc3903b](https://github.com/sergeyshmakov/mineru-runpod/commit/bc3903b1f239f8f6eccc64b1f6a8c631cfe487f9))

### Documentation

* update docs links ([6a7be0a](https://github.com/sergeyshmakov/mineru-runpod/commit/6a7be0ad998389e9bb263e395cc435316e56ce58))

## [1.1.0](https://github.com/sergeyshmakov/mineru-runpod/compare/v1.0.0...v1.1.0) (2026-05-19)

### Features

* **docs:** add Choosing a GPU guide ([3aa6506](https://github.com/sergeyshmakov/mineru-runpod/commit/3aa650650fa91a79472b25f76e027428a7b93752))

## 1.0.0 (2026-05-19)

### Features

* **docs:** scaffold Astro + Starlight site with launch blog post ([aaeaa27](https://github.com/sergeyshmakov/mineru-runpod/commit/aaeaa27eed2912928fc068b44b7709842714a482))
* prepare mineru-runpod for public RunPod Hub launch ([9690fe9](https://github.com/sergeyshmakov/mineru-runpod/commit/9690fe9956665dfe0d53cec494c541c1ce5a398e))

# Changelog

All notable changes to this project will be documented in this file.

This file is **maintained automatically** by [semantic-release](https://semantic-release.gitbook.io/) from the commit history. Do not edit it by hand — commit using [Conventional Commits](https://www.conventionalcommits.org/) and the next release will append the right entry.

<!-- semantic-release-replace-marker — DO NOT REMOVE -->
