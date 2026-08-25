<template>
  <el-result icon="warning" title="无权访问" sub-title="当前账号没有此页面的功能权限">
    <template #extra><el-button type="primary" @click="$router.back()">返回</el-button></template>
  </el-result>
</template>
