# frozen_string_literal: true

module API
  module Entities
    class UserBasic < UserSafe
      expose :state
      expose :avatar_url
      expose :web_url
      expose :job_title, if: ->(_, options) { options[:with_job_title] }
    end
  end
end
