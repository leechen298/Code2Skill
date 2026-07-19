---
name: sample-request
title: 合成请求后端能力与安全边界说明
description: 说明一个没有前端页面的合成后端能力如何暴露查询、校验和受保护写入，并帮助 Agent 判断可调用能力、必要宿主设施与停止条件。
surface: backend-api
surface-id: sample-request
route: /__code2skill__/features/sample-request
language: zh-CN
---

# 合成请求后端能力

> 这是结构模板。生成时必须用源码事实扩展至严格长度要求，并删除这条说明。

## 页面定位

<说明真实 feature surface；没有页面时明确写 API、RPC、消息、worker 或其他后端表面。`route` 只是 node-stdio 文档标识，不是运行时地址。>

## 典型用户目标

<列出可以独立完成的局部目标。>

## 页面区域与业务信息

<有页面时说明区域；route-less feature 改为说明入口、请求/消息、状态、结果及其业务含义，不得虚构界面。>

## 动态依赖与失效规则

<说明 ID、token、选项、游标与前序结果何时失效。>

## 可用 MCP 能力

- `<tool_name>`：<独立价值、入参来源、输出用途。>

## Agent 使用边界

<说明不得越过的能力和运行时约束。>

## 副作用与确认

<只读 feature 明确说明没有写入。存在写 Tool 时，每个 Tool 单独一行，例如：`<write_tool>` 只能在可信 Host 确认和运行时 Guard 通过后派发；不得自动重试；派发结果未知或不确定时必须停止并对账。生成时删除不适用的占位内容。>

## 不属于本页面的能力

<明确排除没有源码证据的能力。>

## 推荐起点

<按用户信息完整度给出最小调用起点。>
