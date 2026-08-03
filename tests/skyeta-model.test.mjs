import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const modelUrl = new URL("../public/assets/skyeta-model.json", import.meta.url);

function treeValue(root, features) {
  let node = root;
  for (let depth = 0; depth < 512; depth += 1) {
    if (Number.isFinite(node.leaf_value)) return node.leaf_value;
    const value = features[node.split_feature];
    const threshold = Number(node.threshold);
    const goLeft = Number.isFinite(value)
      ? value <= threshold
      : node.default_left === true;
    node = goLeft ? node.left_child : node.right_child;
  }
  throw new Error("Tree traversal exceeded its depth limit");
}

function probability(model, rawFeatures) {
  const features = rawFeatures.map(Math.fround);
  const raw = model.booster.tree_info.reduce(
    (sum, tree) => sum + treeValue(tree.tree_structure, features),
    0,
  );
  const calibratedRaw = model.formatVersion === 2
    ? model.calibration.slope * raw + model.calibration.intercept
    : raw;
  if (calibratedRaw >= 0) return 1 / (1 + Math.exp(-calibratedRaw));
  const exponential = Math.exp(calibratedRaw);
  return exponential / (1 + exponential);
}

test("browser model reproduces exported LightGBM probabilities", async () => {
  const model = JSON.parse(await readFile(modelUrl, "utf8"));

  assert.ok(model.formatVersion === 1 || model.formatVersion === 2);
  assert.ok(model.featureSet === "core" || model.featureSet === "context");
  assert.equal(model.featureNames.length, model.featureSet === "context" ? 20 : 16);
  if (model.formatVersion === 2) {
    assert.equal(model.calibration.method, "platt_sigmoid");
    assert.equal(model.calibration.input, "lightgbm_raw_score");
    assert.ok(model.calibration.slope > 0);
    assert.equal(model.modelCard.evaluationPolicy.testUsedFor, "final untouched reporting only");
  }
  assert.ok(model.booster.tree_info.length > 0);
  assert.ok(Array.isArray(model.parityCases));
  assert.ok(model.parityCases.length >= 20);
  assert.equal(model.modelCard.source.publisher, "U.S. Bureau of Transportation Statistics");
  assert.ok(model.modelCard.metrics.test.rocAuc > 0.5);
  assert.ok(model.modelCard.metrics.test.rows >= 100_000);

  let maxError = 0;
  for (const fixture of model.parityCases) {
    const error = Math.abs(
      probability(model, fixture.features) - fixture.probability,
    );
    maxError = Math.max(maxError, error);
  }
  assert.ok(maxError <= 1e-10, `maximum parity error was ${maxError}`);
});
