# Changelog

## [0.3.0](https://github.com/KLTsai/next-is-you/compare/v0.2.0...v0.3.0) (2026-11-14)


### Features

* add fixture-driven hospital adapters ([530ab2c](https://github.com/KLTsai/next-is-you/commit/530ab2c3842c2b7222020d0e1a104096589cbfaf))
* add visit persistence lifecycle (NIY-003) ([6440c39](https://github.com/KLTsai/next-is-you/commit/6440c3947565c0ed0c5a925277427bbc4f84b718))
* **ci-cd:** add release-please versioning and tagged production deploy ([5e433e4](https://github.com/KLTsai/next-is-you/commit/5e433e49189d18ea9333f813062bffc24835e7ff))
* **ci-cd:** add release-please versioning and tagged production deploy ([8652200](https://github.com/KLTsai/next-is-you/commit/865220056ab6deb9e714682e0106824f06c32239))
* complete NIY-002 local Worker shell ([81af612](https://github.com/KLTsai/next-is-you/commit/81af612bbe362b601d9895eb0fe8cf0ca7c12674))
* **frontend:** add organizer-managed LINE invitation and member removal UI ([#42](https://github.com/KLTsai/next-is-you/issues/42)) ([259da23](https://github.com/KLTsai/next-is-you/commit/259da23d9b4751d664a4e37b56acf27740285eae))
* **frontend:** catalog-driven cascading reminder-setup UI ([#47](https://github.com/KLTsai/next-is-you/issues/47)) ([#54](https://github.com/KLTsai/next-is-you/issues/54)) ([73260e2](https://github.com/KLTsai/next-is-you/commit/73260e2ba1aedc7a11820c0c2114b01cf6fc968e))
* **frontend:** clarify visit setup and monitoring controls ([#4](https://github.com/KLTsai/next-is-you/issues/4)) ([2be38c4](https://github.com/KLTsai/next-is-you/commit/2be38c40519399219d743fd699616567c2ae1f39))
* **frontend:** collapse saved drafts ([#13](https://github.com/KLTsai/next-is-you/issues/13)) ([49680d2](https://github.com/KLTsai/next-is-you/commit/49680d2e35fc8331a114e28f0d0e040608c44891))
* **frontend:** extend doctor picker to visit dates within schedule window ([c43ffee](https://github.com/KLTsai/next-is-you/commit/c43ffee01bff1aec51122d719e96f4167c340a9b)), closes [#58](https://github.com/KLTsai/next-is-you/issues/58)
* **frontend:** prefill saved patient number in correction ([#11](https://github.com/KLTsai/next-is-you/issues/11)) ([8d8dd95](https://github.com/KLTsai/next-is-you/commit/8d8dd95203b4cbeb27624d46eb89d72fb2c0406e))
* **frontend:** show reminder list count ([#30](https://github.com/KLTsai/next-is-you/issues/30)) ([f97ad5d](https://github.com/KLTsai/next-is-you/commit/f97ad5ddf98db0aae60974e7591490c7cf17d7fd))
* implement alert domain and local Worker shell (NIY-001, NIY-002) ([58118e5](https://github.com/KLTsai/next-is-you/commit/58118e50961c3a9efe3f8a6665d35c65cfdb92d1))
* implement LINE identity and recipient delivery ([74eb905](https://github.com/KLTsai/next-is-you/commit/74eb905709f8498d9e4313cd115f684913a708c1))
* improve organizer drafts and local rehearsal ([#24](https://github.com/KLTsai/next-is-you/issues/24)) ([2457cee](https://github.com/KLTsai/next-is-you/commit/2457cee46c887ffe0a0c0ccc637fcd08ec3984c9))
* **next_is_you:** add NTUH ophthalmology queue reader ([#35](https://github.com/KLTsai/next-is-you/issues/35)) ([baa8baa](https://github.com/KLTsai/next-is-you/commit/baa8baa56edbb9984f5ae272b1c9a588c8ee6a0c))
* **next_is_you:** isolate hospital reading behind a replaceable adapter ([#48](https://github.com/KLTsai/next-is-you/issues/48)) ([5a96d4f](https://github.com/KLTsai/next-is-you/commit/5a96d4ffa64658227e64ce6bde1601f2fafd51a5)), closes [#45](https://github.com/KLTsai/next-is-you/issues/45)
* **next_is_you:** read the live clinic list and bound the watch by its number ([#46](https://github.com/KLTsai/next-is-you/issues/46)) ([cd199d7](https://github.com/KLTsai/next-is-you/commit/cd199d71ed1b227c454f7122f5ee88a4be4418a7)), closes [#34](https://github.com/KLTsai/next-is-you/issues/34)
* **next_is_you:** repeat near reminders as the called number moves ([#33](https://github.com/KLTsai/next-is-you/issues/33)) ([#37](https://github.com/KLTsai/next-is-you/issues/37)) ([8b2bdca](https://github.com/KLTsai/next-is-you/commit/8b2bdca9cf0837ea0d043077c013d41946daacc5))
* **next_is_you:** serve a hospital catalog and clinic roster for the setup picker ([#47](https://github.com/KLTsai/next-is-you/issues/47)) ([#49](https://github.com/KLTsai/next-is-you/issues/49)) ([bec72a5](https://github.com/KLTsai/next-is-you/commit/bec72a5a6900983b782e70f5b947f686f8b25288))
* **next_is_you:** support restarting expired reminders ([#28](https://github.com/KLTsai/next-is-you/issues/28)) ([15533ec](https://github.com/KLTsai/next-is-you/commit/15533ecbfaf5febc6726ee9adbbc979a664255b5))
* **ntuh:** schedule reader for 14-day pre-flight lookahead ([04b0168](https://github.com/KLTsai/next-is-you/commit/04b01687669c4bfbe3213196b4c313b5377b0a8b)), closes [#58](https://github.com/KLTsai/next-is-you/issues/58)
* pre-flight validation to block three setup mistakes before Start ([#58](https://github.com/KLTsai/next-is-you/issues/58)) ([514b03f](https://github.com/KLTsai/next-is-you/commit/514b03f73312a37fa5d9dee57c6539b8c6dedaeb))
* prepare a held HTTPS Worker service ([#31](https://github.com/KLTsai/next-is-you/issues/31)) ([dada0a0](https://github.com/KLTsai/next-is-you/commit/dada0a07d998d0bcc6aba75bb187457a250155d9))
* project trusted hospital source links ([7d6f297](https://github.com/KLTsai/next-is-you/commit/7d6f29712280fd53cea7b170dca3aced98a277fd))
* **scheduler:** daily pre-flight sweep over drafts in schedule window ([3190f15](https://github.com/KLTsai/next-is-you/commit/3190f15274e57350983d786faad2f3fda3084bf1)), closes [#58](https://github.com/KLTsai/next-is-you/issues/58)
* show patient numbers on organizer reminder cards ([#25](https://github.com/KLTsai/next-is-you/issues/25)) ([d32395a](https://github.com/KLTsai/next-is-you/commit/d32395a8d0c282e05026d129ea6b057240238e2e))
* **start:** fail-closed pre-flight validation before monitoring ([f1a58be](https://github.com/KLTsai/next-is-you/commit/f1a58bec23fa1258235d5347a891cd53a598c0fa)), closes [#58](https://github.com/KLTsai/next-is-you/issues/58)


### Bug Fixes

* **ci-cd:** baseline release-please at the current held production commit ([ba145d7](https://github.com/KLTsai/next-is-you/commit/ba145d72a5be91e6eed56e08bb587f2940299995))
* **ci-cd:** baseline release-please at the current held production commit ([f23ebf4](https://github.com/KLTsai/next-is-you/commit/f23ebf4b67d0c567c68aab61b098cf00766bca46))
* **ci-cd:** match production deploy to the prod GitHub Environment ([ab66637](https://github.com/KLTsai/next-is-you/commit/ab6663786bf3f081c33e72b2a2bd162ae6f0d801))
* **ci-cd:** match production deploy to the prod GitHub Environment ([f4bf056](https://github.com/KLTsai/next-is-you/commit/f4bf056b2ea749989f493b2d1ecfe32220d56807))
* **ci:** make promotion verify an annotated candidate tag, not a signature ([25ad420](https://github.com/KLTsai/next-is-you/commit/25ad42053ce192836da5477d546df98373cac3c5))
* **frontend:** clarify failed Start feedback and align date field ([#32](https://github.com/KLTsai/next-is-you/issues/32)) ([d9ddfed](https://github.com/KLTsai/next-is-you/commit/d9ddfedde155e2a09a89b41af9b30f42b3440bff))
* **frontend:** prevent clinic/session data loss during roster load in correction form ([#62](https://github.com/KLTsai/next-is-you/issues/62)) ([c806cff](https://github.com/KLTsai/next-is-you/commit/c806cfff60490f57b03ed1480a286208cbea2547))
* request LINE profile scope for recipient login flow ([#43](https://github.com/KLTsai/next-is-you/issues/43)) ([2b153c5](https://github.com/KLTsai/next-is-you/commit/2b153c5ddcf51c0ce778089bd3399ebc330f6793))
* restore Python Worker startup compatibility ([#5](https://github.com/KLTsai/next-is-you/issues/5)) ([b8b6b7e](https://github.com/KLTsai/next-is-you/commit/b8b6b7e02d588784df25572e773c19277cc58dfd))
* restore reminder correction and draft transitions ([#26](https://github.com/KLTsai/next-is-you/issues/26)) ([999f971](https://github.com/KLTsai/next-is-you/commit/999f971c054129a01156bb37e4b18ee1c08f8213))
* **tests:** add container wait after expand-drafts clicks in rehearsal tests ([#61](https://github.com/KLTsai/next-is-you/issues/61)) ([5aee8a1](https://github.com/KLTsai/next-is-you/commit/5aee8a1471f676ae95630ed460ec05dd767e7293))
* validate stop timestamp before state transition ([acc0900](https://github.com/KLTsai/next-is-you/commit/acc0900efb59d2e8a42a253e4ad6e2edbf424c1e))
* **worker:** prevent HTTP 500 when saving drafts ([#8](https://github.com/KLTsai/next-is-you/issues/8)) ([0089706](https://github.com/KLTsai/next-is-you/commit/008970694eef69a3097af8bfeeb4bedbe7f45868))


### Documentation

* add concrete research source locations ([96f4c8e](https://github.com/KLTsai/next-is-you/commit/96f4c8e6cf7ffed8a9dba2a54b8f8fd99301b727))
* add configuration and repository review tickets ([e01ee05](https://github.com/KLTsai/next-is-you/commit/e01ee05ba142416af6b9abf36cd9523cf8d654aa))
* add durable agent guidance ([#2](https://github.com/KLTsai/next-is-you/issues/2)) ([2d193e3](https://github.com/KLTsai/next-is-you/commit/2d193e36055aabecf9618cb52525247f6a3fa4c9))
* add known limitations to README ([#39](https://github.com/KLTsai/next-is-you/issues/39)) ([7debd51](https://github.com/KLTsai/next-is-you/commit/7debd5176564a55e2d6d6039a9d4972df71673d1))
* add MVP implementation tickets ([9ae5dc8](https://github.com/KLTsai/next-is-you/commit/9ae5dc8be99180b45e24ff1b3764b3c5afbc3c85))
* add NIY-006 env template boundary ([aad3e16](https://github.com/KLTsai/next-is-you/commit/aad3e16ee95577af6f152fa419066a51ce155da5))
* add NIY-010 organizer API ticket ([5843eff](https://github.com/KLTsai/next-is-you/commit/5843effa532e8464ab0312f00086b3b3e7da9efc))
* add NIY-017 removal ticket ([d176ff9](https://github.com/KLTsai/next-is-you/commit/d176ff9826fbb98fb997e56a9ae30a88316b1d84))
* add research navigation index (NIY-014) ([a15bab5](https://github.com/KLTsai/next-is-you/commit/a15bab5738609457432727714a707a0c0229c0c3))
* add trusted progress link ticket ([76d13e2](https://github.com/KLTsai/next-is-you/commit/76d13e2fa5ac30fcc4230a6ac6c6749df6326f58))
* archive local tickets and configure agent skills ([#14](https://github.com/KLTsai/next-is-you/issues/14)) ([b885c9b](https://github.com/KLTsai/next-is-you/commit/b885c9baf689417a37ec4ec9e48dd6eae0b1768d))
* bound NIY-010 source status projection ([9013201](https://github.com/KLTsai/next-is-you/commit/901320107ea9870cbec60ac997689406fbdcfc69))
* clarify NIY-010 automatic notifications ([d5498a0](https://github.com/KLTsai/next-is-you/commit/d5498a01c5d975870febfdfe95be6822f5f63f70))
* clarify private research inventory boundary ([c049520](https://github.com/KLTsai/next-is-you/commit/c0495201cf45511bbdc666d874a6b6b2e6da9a1a))
* close locally validated NIY-001 ([dcb6450](https://github.com/KLTsai/next-is-you/commit/dcb64509f3f9dc3c9ebf080f3c466e76c06f2404))
* **deploy:** reconcile deployment docs with the candidate pipeline ([81697fb](https://github.com/KLTsai/next-is-you/commit/81697fbbdbba5edfbdfed5078c89c828505c5d6f))
* document NIY-021 hospital source findings ([#9](https://github.com/KLTsai/next-is-you/issues/9)) ([647fa49](https://github.com/KLTsai/next-is-you/commit/647fa49ddfbf4219abc3bf4a61eddbfb2652fc4c))
* keep local env file private on machine ([2c71317](https://github.com/KLTsai/next-is-you/commit/2c71317e9e64459a586d542736a6e9867fcbdbad))
* make both language-switch labels real links ([5bc5a2f](https://github.com/KLTsai/next-is-you/commit/5bc5a2f4e0846ca2346cd9970a7df80a49915412))
* mark NIY-003 lifecycle complete ([3c1ccc3](https://github.com/KLTsai/next-is-you/commit/3c1ccc337f2ea9028d29edd150ef1c2bdd88e942))
* mark trusted progress links complete ([cd39397](https://github.com/KLTsai/next-is-you/commit/cd39397666185c638692834eb96306c0e36e9a87))
* note planned CI and governance hardening ([#40](https://github.com/KLTsai/next-is-you/issues/40)) ([742227d](https://github.com/KLTsai/next-is-you/commit/742227d186a989b74a8abda1f899fc2d68ac3e34))
* pre-flight schedule reader, status entry, recovery notes ([b343861](https://github.com/KLTsai/next-is-you/commit/b343861771616614de9ad63e6df09c2080c0f6df)), closes [#58](https://github.com/KLTsai/next-is-you/issues/58)
* **readme:** point first-time readers to self-hosting and reconcile status ([3191b73](https://github.com/KLTsai/next-is-you/commit/3191b732826c7822eff3d371fc7dda942c2863ce))
* record HTTPS service acceptance ([#41](https://github.com/KLTsai/next-is-you/issues/41)) ([fcc7d34](https://github.com/KLTsai/next-is-you/commit/fcc7d34480f814a3f964c0b26353966c2e1b6698))
* remove unrelated NIY-014 ticket ([8a3dcd6](https://github.com/KLTsai/next-is-you/commit/8a3dcd681c8e7a1e39e2a96d4175a1725b071944))
* replace CONTEXT.md references with GLOSSARY.md ([#60](https://github.com/KLTsai/next-is-you/issues/60)) ([ad735cd](https://github.com/KLTsai/next-is-you/commit/ad735cde31ff0dda8d3a18180829714901fb8afc))
* rewrite project README ([#38](https://github.com/KLTsai/next-is-you/issues/38)) ([dcaf515](https://github.com/KLTsai/next-is-you/commit/dcaf515ebc155ad4fe0e6eeefddf3d1580cc5c32))
* start NIY-003 persistence ticket ([e6b36e9](https://github.com/KLTsai/next-is-you/commit/e6b36e960c41d0c76ed1ccdee8f3b61243a7c1ea))
* track current visit setup and hospital source tickets ([d90dc36](https://github.com/KLTsai/next-is-you/commit/d90dc369aeed5102b79ac490416cebb78a532d97))
* track draft correction and saved-draft UX follow-ups ([#6](https://github.com/KLTsai/next-is-you/issues/6)) ([5899d10](https://github.com/KLTsai/next-is-you/commit/5899d1087e88f4c9d8c55fd18aa40105513367c7))

## [0.2.0](https://github.com/KLTsai/next-is-you/compare/v0.1.0...v0.2.0) (2026-10-31)


### Features

* **ci-cd:** add release-please versioning and tagged production deploy ([5e433e4](https://github.com/KLTsai/next-is-you/commit/5e433e49189d18ea9333f813062bffc24835e7ff))
* **ci-cd:** add release-please versioning and tagged production deploy ([8652200](https://github.com/KLTsai/next-is-you/commit/865220056ab6deb9e714682e0106824f06c32239))
* **frontend:** catalog-driven cascading reminder-setup UI ([#47](https://github.com/KLTsai/next-is-you/issues/47)) ([#54](https://github.com/KLTsai/next-is-you/issues/54)) ([73260e2](https://github.com/KLTsai/next-is-you/commit/73260e2ba1aedc7a11820c0c2114b01cf6fc968e))
* **next_is_you:** serve a hospital catalog and clinic roster for the setup picker ([#47](https://github.com/KLTsai/next-is-you/issues/47)) ([#49](https://github.com/KLTsai/next-is-you/issues/49)) ([bec72a5](https://github.com/KLTsai/next-is-you/commit/bec72a5a6900983b782e70f5b947f686f8b25288))


### Bug Fixes

* **ci-cd:** baseline release-please at the current held production commit ([ba145d7](https://github.com/KLTsai/next-is-you/commit/ba145d72a5be91e6eed56e08bb587f2940299995))
* **ci-cd:** baseline release-please at the current held production commit ([f23ebf4](https://github.com/KLTsai/next-is-you/commit/f23ebf4b67d0c567c68aab61b098cf00766bca46))
* **ci-cd:** match production deploy to the prod GitHub Environment ([ab66637](https://github.com/KLTsai/next-is-you/commit/ab6663786bf3f081c33e72b2a2bd162ae6f0d801))
* **ci-cd:** match production deploy to the prod GitHub Environment ([f4bf056](https://github.com/KLTsai/next-is-you/commit/f4bf056b2ea749989f493b2d1ecfe32220d56807))
