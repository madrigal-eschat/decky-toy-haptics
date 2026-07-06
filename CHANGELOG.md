# 1.0.0 (2026-07-06)


### Bug Fixes

* add jsxFragmentFactory to tsconfig ([2178098](https://github.com/madrigal-eschat/decky-toy-haptics/commit/2178098f21464b4b6d8f02f2d9d9d1911c7b7acc))
* correct stale template repository URLs in package.json ([a769c99](https://github.com/madrigal-eschat/decky-toy-haptics/commit/a769c99f2cdc66587bfaa05770b3b30878773c81))
* **haptics-probe:** fix FF_RAMP const, eBPF map leaks, ring-buf busy-poll ([7bf39fd](https://github.com/madrigal-eschat/decky-toy-haptics/commit/7bf39fd3f116e01aed8279c16181b4529545d04d))
* repair haptics-probe Rust build (aya-bpf/aya-ebpf rename, aya-build 0.2 API, RingBuf ownership, translate.rs test bugs) ([bec0fb9](https://github.com/madrigal-eschat/decky-toy-haptics/commit/bec0fb99c97a3aad5b93ed95cd558588831bb619))
* rewrite HapticsBridge and mock_probe fixture, drop broken duplicate Plugin methods and incompatible test_routing.py ([6f52994](https://github.com/madrigal-eschat/decky-toy-haptics/commit/6f529948237bbcad648360c716282d91cb3bcfbf))
* use python3 to unzip intiface-engine (unzip not in holo-base) ([8496f09](https://github.com/madrigal-eschat/decky-toy-haptics/commit/8496f09830386ca00a616fb496f906f1128fa9ef))


### Features

* add Plugin implementation with full backend test suite ([d51b5df](https://github.com/madrigal-eschat/decky-toy-haptics/commit/d51b5df51e52ad74b8d313372168d3feb776555b))
* BridgePanel UI, Task 9/10 test coverage, frontend Playwright tests for bridge ([dfa681b](https://github.com/madrigal-eschat/decky-toy-haptics/commit/dfa681b72d5d585d1853c0c2597382aa3c8954a1))
* download intiface-engine binary in Makefile ([1bc41d9](https://github.com/madrigal-eschat/decky-toy-haptics/commit/1bc41d9f73d42e8b9932cc942dfa64428ec5e80b))
* scaffold haptics-probe Rust workspace ([12e64cb](https://github.com/madrigal-eschat/decky-toy-haptics/commit/12e64cb744e821d943e956bf67d455d51919b289))
