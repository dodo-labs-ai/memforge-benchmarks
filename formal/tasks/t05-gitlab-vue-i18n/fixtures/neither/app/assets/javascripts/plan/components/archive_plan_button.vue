<script>
import { GlButton } from '@gitlab/ui';
import { s__ } from '~/locale';

const LABEL = s__('Plan|Archive plan');

export default {
  name: 'ArchivePlanButton',
  components: { GlButton },
  computed: {
    label() {
      return LABEL;
    },
  },
};
</script>

<template>
  <gl-button @click="$emit('archive')">{{ label }}</gl-button>
</template>
