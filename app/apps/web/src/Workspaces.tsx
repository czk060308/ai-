import { lazy, Suspense } from 'react';
import { Spin } from 'antd';

const Care = lazy(() => import('./App'));
const Meals = lazy(() => import('./MealWorkbench'));

/** 新助餐场景为默认入口；旧需求与其验收入口继续独立可访问。 */
export default function Workspaces() {
  const care = new URLSearchParams(window.location.search).get('scene') === 'care';
  return <><nav className="scene-switcher" aria-label="场景切换">
    <a className={!care ? 'active' : ''} href="/?scene=meal">番禺 · 助餐接力</a>
    <a className={care ? 'active' : ''} href="/?scene=care">原复诊场景</a>
  </nav><Suspense fallback={<Spin fullscreen tip="正在载入工作台" />}>{care ? <Care /> : <Meals />}</Suspense></>;
}
