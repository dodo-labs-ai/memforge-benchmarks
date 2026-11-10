# frozen_string_literal: true

module API
  class Contributors < ::API::Base
    resource :projects do
      desc 'List the contributors of a project'
      get ':id/contributors' do
        users = user_project.contributors

        present paginate(users), with: Entities::UserBasic
      end
    end
  end
end
