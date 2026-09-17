import { describe, expect, it } from "vitest"
import { orderSeries, resolveProductOrders } from "@/src/modules/analytics/product-orders"
import type { RawIssueRow } from "@/src/modules/analytics/types"
const row: RawIssueRow = { sourceSystem:"test",code:"A*3+B*6",productId:"P",name:"组合",p1:"产品问题",p2:"未填写",p3:"未填写",counts:[1,2] }
describe("exact native sales specification", () => {
  it("never borrows base or component denominators", () => {
    const totals = new Map([["A",[100,200]],["B",[300,400]],["A*3",[2,3]]])
    expect(orderSeries("A*6",totals)).toBeUndefined()
    expect(orderSeries("A*3+B*6",totals)).toBeUndefined()
    expect(orderSeries("A*3",totals)).toEqual([2,3])
  })
  it("does not infer a sales link from one issue product ID", () => {
    expect(resolveProductOrders({row,length:2,platformOrders:new Map([["P",[100,200]]]),platformSales:new Map()}).orders).toEqual([null,null])
  })
  it("uses only a proven platform, shop, link and full-spec identity", () => {
    const result=resolveProductOrders({row:{...row,denominatorKey:"proof"},length:2,platformOrders:new Map([["proof",[0,2]]]),platformSales:new Map([["proof",[0,3]]])})
    expect(result).toEqual({orders:[0,2],sales:[0,3],usedFallback:false,unavailable:false})
  })
  it("keeps unavailable periods distinct from real zero", () => {
    expect(resolveProductOrders({row:{...row,denominatorKey:"proof"},length:2,platformOrders:new Map([["proof",[0,null]]]),platformSales:new Map([["proof",[0,null]]])}).orders).toEqual([0,null])
  })
})
