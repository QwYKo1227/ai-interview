import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const componentUrl = new URL('../src/components/JDGeneratorModal/index.tsx', import.meta.url);

test('JD chat success message points to the updated content above', async () => {
  const source = await readFile(componentUrl, 'utf8');

  assert.match(source, /已根据您的要求更新了上方岗位描述。/);
  assert.doesNotMatch(source, /已根据您的要求更新了岗位描述，请查看下方内容。/);
});
