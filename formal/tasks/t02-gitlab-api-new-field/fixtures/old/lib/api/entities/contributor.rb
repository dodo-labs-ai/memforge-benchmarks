module API
  module Entities
    class Contributor < UserBasic
      expose :job_title, documentation: { type: 'String', example: 'Engineer' }
    end
  end
end
