# frozen_string_literal: true

module API
  class Contributors < ::API::Base
    resource :projects do
      desc 'List the contributors of a project'
      params do
        optional :page, type: Integer
      end
      get ':id/contributors' do
        users = user_project.contributors

        present paginate(users), with: Entities::ContributorWithJobTitle
      end
    end
  end
end
