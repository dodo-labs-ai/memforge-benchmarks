<script>
import { GlIcon } from '@gitlab/ui';

export default {
  name: 'PlanStatusIcon',
  components: { GlIcon },
  props: {
    iconName: { type: String, required: true },
  },
};
</script>

<template>
  <gl-icon :name="iconName" />
</template>
